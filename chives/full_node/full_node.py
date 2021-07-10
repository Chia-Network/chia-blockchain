import asyncio
import dataclasses
import logging
import random
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import aiosqlite
from blspy import AugSchemeMPL

import chives.server.ws_connection as ws  # lgtm [py/import-and-import-from]
from chives.consensus.block_creation import unfinished_block_to_full_block
from chives.consensus.block_record import BlockRecord
from chives.consensus.blockchain import Blockchain, ReceiveBlockResult
from chives.consensus.constants import ConsensusConstants
from chives.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chives.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chives.consensus.multiprocess_validation import PreValidationResult
from chives.consensus.pot_iterations import calculate_sp_iters
from chives.full_node.block_store import BlockStore
from chives.full_node.bundle_tools import detect_potential_template_generator
from chives.full_node.coin_store import CoinStore
from chives.full_node.full_node_store import FullNodeStore
from chives.full_node.mempool_manager import MempoolManager
from chives.full_node.signage_point import SignagePoint
from chives.full_node.sync_store import SyncStore
from chives.full_node.weight_proof import WeightProofHandler
from chives.protocols import farmer_protocol, full_node_protocol, timelord_protocol, wallet_protocol
from chives.protocols.full_node_protocol import (
    RejectBlocks,
    RequestBlocks,
    RespondBlock,
    RespondBlocks,
    RespondSignagePoint,
)
from chives.protocols.protocol_message_types import ProtocolMessageTypes
from chives.server.node_discovery import FullNodePeers
from chives.server.outbound_message import Message, NodeType, make_msg
from chives.server.server import ChivesServer
from chives.types.blockchain_format.classgroup import ClassgroupElement
from chives.types.blockchain_format.pool_target import PoolTarget
from chives.types.blockchain_format.sized_bytes import bytes32
from chives.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chives.types.blockchain_format.vdf import CompressibleVDFField, VDFInfo, VDFProof
from chives.types.end_of_slot_bundle import EndOfSubSlotBundle
from chives.types.full_block import FullBlock
from chives.types.header_block import HeaderBlock
from chives.types.mempool_inclusion_status import MempoolInclusionStatus
from chives.types.spend_bundle import SpendBundle
from chives.types.unfinished_block import UnfinishedBlock
from chives.util.bech32m import encode_puzzle_hash
from chives.util.db_wrapper import DBWrapper
from chives.util.errors import ConsensusError, Err
from chives.util.ints import uint8, uint32, uint64, uint128
from chives.util.path import mkdir, path_from_root
from chives.util.safe_cancel_task import cancel_task_safe
from chives.util.profiler import profile_task


class FullNode:
    block_store: BlockStore
    full_node_store: FullNodeStore
    full_node_peers: Optional[FullNodePeers]
    sync_store: Any
    coin_store: CoinStore
    mempool_manager: MempoolManager
    connection: aiosqlite.Connection
    _sync_task: Optional[asyncio.Task]
    _init_weight_proof: Optional[asyncio.Task] = None
    blockchain: Blockchain
    config: Dict
    server: Any
    log: logging.Logger
    constants: ConsensusConstants
    _shut_down: bool
    root_path: Path
    state_changed_callback: Optional[Callable]
    timelord_lock: asyncio.Lock
    initialized: bool
    weight_proof_handler: Optional[WeightProofHandler]
    _ui_tasks: Set[asyncio.Task]

    def __init__(
        self,
        config: Dict,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
    ):
        self.initialized = False
        self.root_path = root_path
        self.config = config
        self.server = None
        self._shut_down = False  # Set to true to close all infinite loops
        self.constants = consensus_constants
        self.pow_creation: Dict[uint32, asyncio.Event] = {}
        self.state_changed_callback: Optional[Callable] = None
        self.full_node_peers = None
        self.sync_store = None
        self.signage_point_times = [time.time() for _ in range(self.constants.NUM_SPS_SUB_SLOT)]
        self.full_node_store = FullNodeStore(self.constants)

        self.log = logging.getLogger(name if name else __name__)

        self._ui_tasks = set()

        db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
        self.db_path = path_from_root(root_path, db_path_replaced)
        mkdir(self.db_path.parent)

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    async def _start(self):
        self.timelord_lock = asyncio.Lock()
        self.compact_vdf_sem = asyncio.Semaphore(4)
        self.new_peak_sem = asyncio.Semaphore(8)
        # create the store (db) and full node instance
        self.connection = await aiosqlite.connect(self.db_path)
        self.db_wrapper = DBWrapper(self.connection)
        self.block_store = await BlockStore.create(self.db_wrapper)
        self.sync_store = await SyncStore.create()
        self.coin_store = await CoinStore.create(self.db_wrapper)
        self.log.info("Initializing blockchain from disk")
        start_time = time.time()
        self.blockchain = await Blockchain.create(self.coin_store, self.block_store, self.constants)
        self.mempool_manager = MempoolManager(self.coin_store, self.constants)
        self.weight_proof_handler = None
        self._init_weight_proof = asyncio.create_task(self.initialize_weight_proof())

        if self.config.get("enable_profiler", False):
            asyncio.create_task(profile_task(self.root_path, "node", self.log))

        self._sync_task = None
        self._segment_task = None
        time_taken = time.time() - start_time
        if self.blockchain.get_peak() is None:
            self.log.info(f"Initialized with empty blockchain time taken: {int(time_taken)}s")
        else:
            self.log.info(
                f"Blockchain initialized to peak {self.blockchain.get_peak().header_hash} height"
                f" {self.blockchain.get_peak().height}, "
                f"time taken: {int(time_taken)}s"
            )
            pending_tx = await self.mempool_manager.new_peak(self.blockchain.get_peak())
            assert len(pending_tx) == 0  # no pending transactions when starting up

        peak: Optional[BlockRecord] = self.blockchain.get_peak()
        self.uncompact_task = None
        if peak is not None:
            full_peak = await self.blockchain.get_full_peak()
            await self.peak_post_processing(full_peak, peak, max(peak.height - 1, 0), None)
        if self.config["send_uncompact_interval"] != 0:
            sanitize_weight_proof_only = False
            if "sanitize_weight_proof_only" in self.config:
                sanitize_weight_proof_only = self.config["sanitize_weight_proof_only"]
            assert self.config["target_uncompact_proofs"] != 0
            self.uncompact_task = asyncio.create_task(
                self.broadcast_uncompact_blocks(
                    self.config["send_uncompact_interval"],
                    self.config["target_uncompact_proofs"],
                    sanitize_weight_proof_only,
                )
            )
        self.initialized = True
        if self.full_node_peers is not None:
            asyncio.create_task(self.full_node_peers.start())

    async def initialize_weight_proof(self):
        self.weight_proof_handler = WeightProofHandler(self.constants, self.blockchain)
        peak = self.blockchain.get_peak()
        if peak is not None:
            await self.weight_proof_handler.create_sub_epoch_segments()

    def set_server(self, server: ChivesServer):
        self.server = server
        dns_servers = []
        try:
            network_name = self.config["selected_network"]
            default_port = self.config["network_overrides"]["config"][network_name]["default_full_node_port"]
        except Exception:
            self.log.info("Default port field not found in config.")
            default_port = None
        if "dns_servers" in self.config:
            dns_servers = self.config["dns_servers"]
        elif self.config["port"] == 9699:
            # If `dns_servers` misses from the `config`, hardcode it if we're running mainnet.
            dns_servers.append("dns-introducer.chivescoin.org")
        try:
            self.full_node_peers = FullNodePeers(
                self.server,
                self.root_path,
                self.config["target_peer_count"] - self.config["target_outbound_peer_count"],
                self.config["target_outbound_peer_count"],
                self.config["peer_db_path"],
                self.config["introducer_peer"],
                dns_servers,
                self.config["peer_connect_interval"],
                self.config["selected_network"],
                default_port,
                self.log,
            )
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            self.log.error(f"Exception in peer discovery: {e}")
            self.log.error(f"Exception Stack: {error_stack}")

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    async def short_sync_batch(self, peer: ws.WSChivesConnection, start_height: uint32, target_height: uint32) -> bool:
        """
        Tries to sync to a chain which is not too far in the future, by downloading batches of blocks. If the first
        block that we download is not connected to our chain, we return False and do an expensive long sync instead.
        Long sync is not preferred because it requires downloading and validating a weight proof.

        Args:
            peer: peer to sync from
            start_height: height that we should start downloading at. (Our peak is higher)
            target_height: target to sync to

        Returns:
            False if the fork point was not found, and we need to do a long sync. True otherwise.

        """
        # Don't trigger multiple batch syncs to the same peer

        if (
            peer.peer_node_id in self.sync_store.backtrack_syncing
            and self.sync_store.backtrack_syncing[peer.peer_node_id] > 0
        ):
            return True  # Don't batch sync, we are already in progress of a backtrack sync
        if peer.peer_node_id in self.sync_store.batch_syncing:
            return True  # Don't trigger a long sync
        self.sync_store.batch_syncing.add(peer.peer_node_id)

        self.log.info(f"Starting batch short sync from {start_height} to height {target_height}")
        if start_height > 0:
            first = await peer.request_block(full_node_protocol.RequestBlock(uint32(start_height), False))
            if first is None or not isinstance(first, full_node_protocol.RespondBlock):
                self.sync_store.batch_syncing.remove(peer.peer_node_id)
                raise ValueError(f"Error short batch syncing, could not fetch block at height {start_height}")
            if not self.blockchain.contains_block(first.block.prev_header_hash):
                self.log.info("Batch syncing stopped, this is a deep chain")
                self.sync_store.batch_syncing.remove(peer.peer_node_id)
                # First sb not connected to our blockchain, do a long sync instead
                return False

        batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
        if self._segment_task is not None and (not self._segment_task.done()):
            try:
                self._segment_task.cancel()
            except Exception as e:
                self.log.warning(f"failed to cancel segment task {e}")
            self._segment_task = None

        try:
            for height in range(start_height, target_height, batch_size):
                end_height = min(target_height, height + batch_size)
                request = RequestBlocks(uint32(height), uint32(end_height), True)
                response = await peer.request_blocks(request)
                if not response:
                    raise ValueError(f"Error short batch syncing, invalid/no response for {height}-{end_height}")
                async with self.blockchain.lock:
                    success, advanced_peak, fork_height = await self.receive_block_batch(response.blocks, peer, None)
                    if not success:
                        raise ValueError(f"Error short batch syncing, failed to validate blocks {height}-{end_height}")
                    if advanced_peak:
                        peak = self.blockchain.get_peak()
                        peak_fb: Optional[FullBlock] = await self.blockchain.get_full_peak()
                        assert peak is not None and peak_fb is not None and fork_height is not None
                        await self.peak_post_processing(peak_fb, peak, fork_height, peer)
                        self.log.info(f"Added blocks {height}-{end_height}")
        except Exception:
            self.sync_store.batch_syncing.remove(peer.peer_node_id)
            raise
        self.sync_store.batch_syncing.remove(peer.peer_node_id)
        return True

    async def short_sync_backtrack(
        self, peer: ws.WSChivesConnection, peak_height: uint32, target_height: uint32, target_unf_hash: bytes32
    ):
        """
        Performs a backtrack sync, where blocks are downloaded one at a time from newest to oldest. If we do not
        find the fork point 5 deeper than our peak, we return False and do a long sync instead.

        Args:
            peer: peer to sync from
            peak_height: height of our peak
            target_height: target height
            target_unf_hash: partial hash of the unfinished block of the target

        Returns:
            True iff we found the fork point, and we do not need to long sync.
        """
        try:
            if peer.peer_node_id not in self.sync_store.backtrack_syncing:
                self.sync_store.backtrack_syncing[peer.peer_node_id] = 0
            self.sync_store.backtrack_syncing[peer.peer_node_id] += 1

            unfinished_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(target_unf_hash)
            curr_height: int = target_height
            found_fork_point = False
            responses = []
            while curr_height > peak_height - 5:
                # If we already have the unfinished block, don't fetch the transactions. In the normal case, we will
                # already have the unfinished block, from when it was broadcast, so we just need to download the header,
                # but not the transactions
                fetch_tx: bool = unfinished_block is None or curr_height != target_height
                curr = await peer.request_block(full_node_protocol.RequestBlock(uint32(curr_height), fetch_tx))
                if curr is None:
                    raise ValueError(f"Failed to fetch block {curr_height} from {peer.get_peer_info()}, timed out")
                if curr is None or not isinstance(curr, full_node_protocol.RespondBlock):
                    raise ValueError(
                        f"Failed to fetch block {curr_height} from {peer.get_peer_info()}, wrong type {type(curr)}"
                    )
                responses.append(curr)
                if self.blockchain.contains_block(curr.block.prev_header_hash) or curr_height == 0:
                    found_fork_point = True
                    break
                curr_height -= 1
            if found_fork_point:
                for response in reversed(responses):
                    await self.respond_block(response, peer)
        except Exception as e:
            self.sync_store.backtrack_syncing[peer.peer_node_id] -= 1
            raise e

        self.sync_store.backtrack_syncing[peer.peer_node_id] -= 1
        return found_fork_point

    async def _refresh_ui_connections(self, sleep_before: float = 0):
        if sleep_before > 0:
            await asyncio.sleep(sleep_before)
        self._state_changed("peer_changed_peak")

    async def new_peak(self, request: full_node_protocol.NewPeak, peer: ws.WSChivesConnection):
        """
        We have received a notification of a new peak from a peer. This happens either when we have just connected,
        or when the peer has updated their peak.

        Args:
            request: information about the new peak
            peer: peer that sent the message

        """

        try:
            seen_header_hash = self.sync_store.seen_header_hash(request.header_hash)
            # Updates heights in the UI. Sleeps 1.5s before, so other peers have time to update their peaks as well.
            # Limit to 3 refreshes.
            if not seen_header_hash and len(self._ui_tasks) < 3:
                self._ui_tasks.add(asyncio.create_task(self._refresh_ui_connections(1.5)))
            # Prune completed connect tasks
            self._ui_tasks = set(filter(lambda t: not t.done(), self._ui_tasks))
        except Exception as e:
            self.log.warning(f"Exception UI refresh task: {e}")

        # Store this peak/peer combination in case we want to sync to it, and to keep track of peers
        self.sync_store.peer_has_block(request.header_hash, peer.peer_node_id, request.weight, request.height, True)

        if self.blockchain.contains_block(request.header_hash):
            return None

        # Not interested in less heavy peaks
        peak: Optional[BlockRecord] = self.blockchain.get_peak()
        curr_peak_height = uint32(0) if peak is None else peak.height
        if peak is not None and peak.weight > request.weight:
            return None

        if self.sync_store.get_sync_mode():
            # If peer connects while we are syncing, check if they have the block we are syncing towards
            peak_sync_hash = self.sync_store.get_sync_target_hash()
            peak_sync_height = self.sync_store.get_sync_target_height()
            if peak_sync_hash is not None and request.header_hash != peak_sync_hash and peak_sync_height is not None:
                peak_peers: Set[bytes32] = self.sync_store.get_peers_that_have_peak([peak_sync_hash])
                # Don't ask if we already know this peer has the peak
                if peer.peer_node_id not in peak_peers:
                    target_peak_response: Optional[RespondBlock] = await peer.request_block(
                        full_node_protocol.RequestBlock(uint32(peak_sync_height), False), timeout=10
                    )
                    if target_peak_response is not None and isinstance(target_peak_response, RespondBlock):
                        self.sync_store.peer_has_block(
                            peak_sync_hash,
                            peer.peer_node_id,
                            target_peak_response.block.weight,
                            peak_sync_height,
                            False,
                        )
        else:
            if request.height <= curr_peak_height + self.config["short_sync_blocks_behind_threshold"]:
                # This is the normal case of receiving the next block
                if await self.short_sync_backtrack(
                    peer, curr_peak_height, request.height, request.unfinished_reward_block_hash
                ):
                    return None

            if request.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
                # This is the case of syncing up more than a few blocks, at the start of the chain
                # TODO(almog): fix weight proofs so they work at the beginning as well
                self.log.debug("Doing batch sync, no backup")
                await self.short_sync_batch(peer, uint32(0), request.height)
                return None

            if request.height < curr_peak_height + self.config["sync_blocks_behind_threshold"]:
                # This case of being behind but not by so much
                if await self.short_sync_batch(peer, uint32(max(curr_peak_height - 6, 0)), request.height):
                    return None

            # This is the either the case where we were not able to sync successfully (for example, due to the fork
            # point being in the past), or we are very far behind. Performs a long sync.
            self._sync_task = asyncio.create_task(self._sync())

    async def send_peak_to_timelords(
        self, peak_block: Optional[FullBlock] = None, peer: Optional[ws.WSChivesConnection] = None
    ):
        """
        Sends current peak to timelords
        """
        if peak_block is None:
            peak_block = await self.blockchain.get_full_peak()
        if peak_block is not None:
            peak = self.blockchain.block_record(peak_block.header_hash)
            difficulty = self.blockchain.get_next_difficulty(peak.header_hash, False)
            ses: Optional[SubEpochSummary] = next_sub_epoch_summary(
                self.constants,
                self.blockchain,
                peak.required_iters,
                peak_block,
                True,
            )
            recent_rc = self.blockchain.get_recent_reward_challenges()

            curr = peak
            while not curr.is_challenge_block(self.constants) and not curr.first_in_sub_slot:
                curr = self.blockchain.block_record(curr.prev_hash)

            if curr.is_challenge_block(self.constants):
                last_csb_or_eos = curr.total_iters
            else:
                last_csb_or_eos = curr.ip_sub_slot_total_iters(self.constants)

            curr = peak
            passed_ses_height_but_not_yet_included = True
            while (curr.height % self.constants.SUB_EPOCH_BLOCKS) != 0:
                if curr.sub_epoch_summary_included:
                    passed_ses_height_but_not_yet_included = False
                curr = self.blockchain.block_record(curr.prev_hash)
            if curr.sub_epoch_summary_included or curr.height == 0:
                passed_ses_height_but_not_yet_included = False

            timelord_new_peak: timelord_protocol.NewPeakTimelord = timelord_protocol.NewPeakTimelord(
                peak_block.reward_chain_block,
                difficulty,
                peak.deficit,
                peak.sub_slot_iters,
                ses,
                recent_rc,
                last_csb_or_eos,
                passed_ses_height_but_not_yet_included,
            )

            msg = make_msg(ProtocolMessageTypes.new_peak_timelord, timelord_new_peak)
            if peer is None:
                await self.server.send_to_all([msg], NodeType.TIMELORD)
            else:
                await self.server.send_to_specific([msg], peer.peer_node_id)

    async def synced(self) -> bool:
        curr: Optional[BlockRecord] = self.blockchain.get_peak()
        if curr is None:
            return False
        peakBlock = curr
        # self.log.warning(f"peakBlock.height:{peakBlock.height} peakBlock.prev_hash:{peakBlock.prev_hash} peakBlock.timestamp:{peakBlock.timestamp} peakBlock.is_transaction_block: {peakBlock.is_transaction_block}. ")
        
        while curr is not None and not curr.is_transaction_block:
            curr = self.blockchain.try_block_record(curr.prev_hash)
        
        # self.log.warning(f"curr.height:{curr.height} curr.prev_hash:{curr.prev_hash} curr.timestamp:{curr.timestamp} curr.is_transaction_block: {curr.is_transaction_block}. ")
        now = time.time()
        
        if (
            curr is None
            or curr.timestamp is None
            or curr.timestamp < uint64(int(now - 60 * 7))
            or self.sync_store.get_sync_mode()
        ):
            # self.log.warning(f"curr is None:{curr is None}. ")
            # self.log.warning(f"curr.timestamp is None:{curr.timestamp is None}. ")
            # self.log.warning(f"curr.timestamp < uint64(int(now - 60 * 7)):{curr.timestamp < uint64(int(now - 60 * 7))}. ")
            # self.log.warning(f"self.sync_store.get_sync_mode():{self.sync_store.get_sync_mode()}. ")
            return False
        else:
            # self.log.warning(f"Full Node Status: Return Synced. ")
            return True

    async def on_connect(self, connection: ws.WSChivesConnection):
        """
        Whenever we connect to another node / wallet, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """

        self._state_changed("add_connection")
        self._state_changed("sync_mode")
        if self.full_node_peers is not None:
            asyncio.create_task(self.full_node_peers.on_connect(connection))
        
        # Chives Network Code 
        # To Ban The Other Fork Of Chia To Join In
        if connection.peer_port == 9444 or connection.peer_server_port == 9444 or connection.peer_port == 8444 or connection.peer_server_port == 8444 or connection.peer_port == 6888 or connection.peer_server_port == 6888 or connection.peer_port == 8744 or connection.peer_server_port == 8744:  
            self.log.warning(f"Removing The Other Fork Of Chia {connection.peer_host} {connection.peer_port} Connection Type: {connection.connection_type}. ")
            return None
        
        if self.initialized is False:
            return None

        if connection.connection_type is NodeType.FULL_NODE:
            # Send filter to node and request mempool items that are not in it (Only if we are currently synced)
            synced = await self.synced()
            peak_height = self.blockchain.get_peak_height()
            current_time = int(time.time())
            if synced and peak_height is not None and current_time > self.constants.INITIAL_FREEZE_END_TIMESTAMP:
                my_filter = self.mempool_manager.get_filter()
                mempool_request = full_node_protocol.RequestMempoolTransactions(my_filter)

                msg = make_msg(ProtocolMessageTypes.request_mempool_transactions, mempool_request)
                await connection.send_message(msg)

        peak_full: Optional[FullBlock] = await self.blockchain.get_full_peak()

        if peak_full is not None:
            peak: BlockRecord = self.blockchain.block_record(peak_full.header_hash)
            if connection.connection_type is NodeType.FULL_NODE:
                request_node = full_node_protocol.NewPeak(
                    peak.header_hash,
                    peak.height,
                    peak.weight,
                    peak.height,
                    peak_full.reward_chain_block.get_unfinished().get_hash(),
                )
                await connection.send_message(make_msg(ProtocolMessageTypes.new_peak, request_node))

            elif connection.connection_type is NodeType.WALLET:
                # If connected to a wallet, send the Peak
                request_wallet = wallet_protocol.NewPeakWallet(
                    peak.header_hash,
                    peak.height,
                    peak.weight,
                    peak.height,
                )
                await connection.send_message(make_msg(ProtocolMessageTypes.new_peak_wallet, request_wallet))
            elif connection.connection_type is NodeType.TIMELORD:
                await self.send_peak_to_timelords()

    def on_disconnect(self, connection: ws.WSChivesConnection):
        self.log.info(f"peer disconnected {connection.get_peer_info()}")
        self._state_changed("close_connection")
        self._state_changed("sync_mode")
        if self.sync_store is not None:
            self.sync_store.peer_disconnected(connection.peer_node_id)

    def _num_needed_peers(self) -> int:
        assert self.server is not None
        assert self.server.all_connections is not None
        diff = self.config["target_peer_count"] - len(self.server.all_connections)
        return diff if diff >= 0 else 0

    def _close(self):
        self._shut_down = True
        if self._init_weight_proof is not None:
            self._init_weight_proof.cancel()
        if self.blockchain is not None:
            self.blockchain.shut_down()
        if self.mempool_manager is not None:
            self.mempool_manager.shut_down()
        if self.full_node_peers is not None:
            asyncio.create_task(self.full_node_peers.close())
        if self.uncompact_task is not None:
            self.uncompact_task.cancel()

    async def _await_closed(self):
        cancel_task_safe(self._sync_task, self.log)
        for task_id, task in list(self.full_node_store.tx_fetch_tasks.items()):
            cancel_task_safe(task, self.log)
        await self.connection.close()
        if self._init_weight_proof is not None:
            await asyncio.wait([self._init_weight_proof])

    async def _sync(self):
        """
        Performs a full sync of the blockchain up to the peak.
            - Wait a few seconds for peers to send us their peaks
            - Select the heaviest peak, and request a weight proof from a peer with that peak
            - Validate the weight proof, and disconnect from the peer if invalid
            - Find the fork point to see where to start downloading blocks
            - Download blocks in batch (and in parallel) and verify them one at a time
            - Disconnect peers that provide invalid blocks or don't have the blocks
        """
        if self.weight_proof_handler is None:
            return None
        # Ensure we are only syncing once and not double calling this method
        if self.sync_store.get_sync_mode():
            return None

        if self.sync_store.get_long_sync():
            self.log.debug("already in long sync")
            return None

        self.sync_store.set_long_sync(True)
        self.log.debug("long sync started")
        try:
            self.log.info("Starting to perform sync.")
            self.log.info("Waiting to receive peaks from peers.")

            # Wait until we have 3 peaks or up to a max of 30 seconds
            peaks = []
            for i in range(300):
                peaks = [tup[0] for tup in self.sync_store.get_peak_of_each_peer().values()]
                if len(self.sync_store.get_peers_that_have_peak(peaks)) < 3:
                    if self._shut_down:
                        return None
                    await asyncio.sleep(0.1)

            self.log.info(f"Collected a total of {len(peaks)} peaks.")
            self.sync_peers_handler = None

            # Based on responses from peers about the current peaks, see which peak is the heaviest
            # (similar to longest chain rule).
            target_peak = self.sync_store.get_heaviest_peak()

            if target_peak is None:
                raise RuntimeError("Not performing sync, no peaks collected")
            heaviest_peak_hash, heaviest_peak_height, heaviest_peak_weight = target_peak
            self.sync_store.set_peak_target(heaviest_peak_hash, heaviest_peak_height)

            self.log.info(f"Selected peak {heaviest_peak_height}, {heaviest_peak_hash}")
            # Check which peers are updated to this height

            peers = []
            coroutines = []
            for peer in self.server.all_connections.values():
                if peer.connection_type == NodeType.FULL_NODE:
                    peers.append(peer.peer_node_id)
                    coroutines.append(
                        peer.request_block(
                            full_node_protocol.RequestBlock(uint32(heaviest_peak_height), True), timeout=10
                        )
                    )
            for i, target_peak_response in enumerate(await asyncio.gather(*coroutines)):
                if target_peak_response is not None and isinstance(target_peak_response, RespondBlock):
                    self.sync_store.peer_has_block(
                        heaviest_peak_hash, peers[i], heaviest_peak_weight, heaviest_peak_height, False
                    )
            # TODO: disconnect from peer which gave us the heaviest_peak, if nobody has the peak

            peer_ids: Set[bytes32] = self.sync_store.get_peers_that_have_peak([heaviest_peak_hash])
            peers_with_peak: List = [c for c in self.server.all_connections.values() if c.peer_node_id in peer_ids]

            # Request weight proof from a random peer
            self.log.info(f"Total of {len(peers_with_peak)} peers with peak {heaviest_peak_height}")
            weight_proof_peer = random.choice(peers_with_peak)
            self.log.info(
                f"Requesting weight proof from peer {weight_proof_peer.peer_host} up to height"
                f" {heaviest_peak_height}"
            )

            if self.blockchain.get_peak() is not None and heaviest_peak_weight <= self.blockchain.get_peak().weight:
                raise ValueError("Not performing sync, already caught up.")

            wp_timeout = 360
            if "weight_proof_timeout" in self.config:
                wp_timeout = self.config["weight_proof_timeout"]
            self.log.debug(f"weight proof timeout is {wp_timeout} sec")
            request = full_node_protocol.RequestProofOfWeight(heaviest_peak_height, heaviest_peak_hash)
            response = await weight_proof_peer.request_proof_of_weight(request, timeout=wp_timeout)

            # Disconnect from this peer, because they have not behaved properly
            if response is None or not isinstance(response, full_node_protocol.RespondProofOfWeight):
                await weight_proof_peer.close(600)
                raise RuntimeError(f"Weight proof did not arrive in time from peer: {weight_proof_peer.peer_host}")
            if response.wp.recent_chain_data[-1].reward_chain_block.height != heaviest_peak_height:
                await weight_proof_peer.close(600)
                raise RuntimeError(f"Weight proof had the wrong height: {weight_proof_peer.peer_host}")
            if response.wp.recent_chain_data[-1].reward_chain_block.weight != heaviest_peak_weight:
                await weight_proof_peer.close(600)
                raise RuntimeError(f"Weight proof had the wrong weight: {weight_proof_peer.peer_host}")

            # dont sync to wp if local peak is heavier,
            # dont ban peer, we asked for this peak
            current_peak = self.blockchain.get_peak()
            if current_peak is not None:
                if response.wp.recent_chain_data[-1].reward_chain_block.weight <= current_peak.weight:
                    raise RuntimeError(f"current peak is heavier than Weight proof peek: {weight_proof_peer.peer_host}")

            try:
                validated, fork_point, summaries = await self.weight_proof_handler.validate_weight_proof(response.wp)
            except Exception as e:
                await weight_proof_peer.close(600)
                raise ValueError(f"Weight proof validation threw an error {e}")

            if not validated:
                await weight_proof_peer.close(600)
                raise ValueError("Weight proof validation failed")

            self.log.info(f"Re-checked peers: total of {len(peers_with_peak)} peers with peak {heaviest_peak_height}")
            self.sync_store.set_sync_mode(True)
            self._state_changed("sync_mode")
            # Ensures that the fork point does not change
            async with self.blockchain.lock:
                await self.blockchain.warmup(fork_point)
                await self.sync_from_fork_point(fork_point, heaviest_peak_height, heaviest_peak_hash, summaries)
        except asyncio.CancelledError:
            self.log.warning("Syncing failed, CancelledError")
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Error with syncing: {type(e)}{tb}")
        finally:
            if self._shut_down:
                return None
            await self._finish_sync()

    async def sync_from_fork_point(
        self,
        fork_point_height: int,
        target_peak_sb_height: uint32,
        peak_hash: bytes32,
        summaries: List[SubEpochSummary],
    ):
        self.log.info(f"Start syncing from fork point at {fork_point_height} up to {target_peak_sb_height}")
        peer_ids: Set[bytes32] = self.sync_store.get_peers_that_have_peak([peak_hash])
        peers_with_peak: List = [c for c in self.server.all_connections.values() if c.peer_node_id in peer_ids]

        if len(peers_with_peak) == 0:
            raise RuntimeError(f"Not syncing, no peers with header_hash {peak_hash} ")
        advanced_peak = False
        batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS

        our_peak_height = self.blockchain.get_peak_height()
        ses_heigths = self.blockchain.get_ses_heights()
        if len(ses_heigths) > 2 and our_peak_height is not None:
            ses_heigths.sort()
            max_fork_ses_height = ses_heigths[-3]
            # This is the fork point in SES in the case where no fork was detected
            if self.blockchain.get_peak_height() is not None and fork_point_height == max_fork_ses_height:
                for peer in peers_with_peak:
                    # Grab a block at peak + 1 and check if fork point is actually our current height
                    block_response: Optional[Any] = await peer.request_block(
                        full_node_protocol.RequestBlock(uint32(our_peak_height + 1), True)
                    )
                    if block_response is not None and isinstance(block_response, full_node_protocol.RespondBlock):
                        peak = self.blockchain.get_peak()
                        if peak is not None and block_response.block.prev_header_hash == peak.header_hash:
                            fork_point_height = our_peak_height
                        break

        for i in range(fork_point_height, target_peak_sb_height, batch_size):
            start_height = i
            end_height = min(target_peak_sb_height, start_height + batch_size)
            request = RequestBlocks(uint32(start_height), uint32(end_height), True)
            self.log.info(f"Requesting blocks: {start_height} to {end_height}")
            batch_added = False
            to_remove = []
            for peer in peers_with_peak:
                if peer.closed:
                    to_remove.append(peer)
                    continue
                response = await peer.request_blocks(request, timeout=60)
                if response is None:
                    await peer.close()
                    to_remove.append(peer)
                    continue
                if isinstance(response, RejectBlocks):
                    to_remove.append(peer)
                    continue
                elif isinstance(response, RespondBlocks):
                    success, advanced_peak, _ = await self.receive_block_batch(
                        response.blocks, peer, None if advanced_peak else uint32(fork_point_height), summaries
                    )
                    if success is False:
                        await peer.close(600)
                        continue
                    else:
                        batch_added = True
                        break

            peak = self.blockchain.get_peak()
            assert peak is not None
            msg = make_msg(
                ProtocolMessageTypes.new_peak_wallet,
                wallet_protocol.NewPeakWallet(
                    peak.header_hash,
                    peak.height,
                    peak.weight,
                    uint32(max(peak.height - 1, uint32(0))),
                ),
            )
            await self.server.send_to_all([msg], NodeType.WALLET)

            for peer in to_remove:
                peers_with_peak.remove(peer)

            if self.sync_store.peers_changed.is_set():
                peer_ids = self.sync_store.get_peers_that_have_peak([peak_hash])
                peers_with_peak = [c for c in self.server.all_connections.values() if c.peer_node_id in peer_ids]
                self.log.info(f"Number of peers we are syncing from: {len(peers_with_peak)}")
                self.sync_store.peers_changed.clear()

            if batch_added is False:
                self.log.info(f"Failed to fetch blocks {start_height} to {end_height} from peers: {peers_with_peak}")
                break
            else:
                self.log.info(f"Added blocks {start_height} to {end_height}")
                self.blockchain.clean_block_record(
                    min(
                        end_height - self.constants.BLOCKS_CACHE_SIZE,
                        peak.height - self.constants.BLOCKS_CACHE_SIZE,
                    )
                )

    async def receive_block_batch(
        self,
        all_blocks: List[FullBlock],
        peer: ws.WSChivesConnection,
        fork_point: Optional[uint32],
        wp_summaries: Optional[List[SubEpochSummary]] = None,
    ) -> Tuple[bool, bool, Optional[uint32]]:
        advanced_peak = False
        fork_height: Optional[uint32] = uint32(0)

        blocks_to_validate: List[FullBlock] = []
        for i, block in enumerate(all_blocks):
            if not self.blockchain.contains_block(block.header_hash):
                blocks_to_validate = all_blocks[i:]
                break
        if len(blocks_to_validate) == 0:
            return True, False, fork_height

        pre_validate_start = time.time()
        pre_validation_results: Optional[
            List[PreValidationResult]
        ] = await self.blockchain.pre_validate_blocks_multiprocessing(blocks_to_validate, {}, wp_summaries=wp_summaries)
        self.log.debug(f"Block pre-validation time: {time.time() - pre_validate_start}")
        if pre_validation_results is None:
            return False, False, None
        for i, block in enumerate(blocks_to_validate):
            if pre_validation_results[i].error is not None:
                self.log.error(
                    f"Invalid block from peer: {peer.get_peer_info()} {Err(pre_validation_results[i].error)}"
                )
                return False, advanced_peak, fork_height

        for i, block in enumerate(blocks_to_validate):
            assert pre_validation_results[i].required_iters is not None
            (result, error, fork_height,) = await self.blockchain.receive_block(
                block, pre_validation_results[i], None if advanced_peak else fork_point
            )
            if result == ReceiveBlockResult.NEW_PEAK:
                advanced_peak = True
            elif result == ReceiveBlockResult.INVALID_BLOCK or result == ReceiveBlockResult.DISCONNECTED_BLOCK:
                if error is not None:
                    self.log.error(f"Error: {error}, Invalid block from peer: {peer.get_peer_info()} ")
                return False, advanced_peak, fork_height
            block_record = self.blockchain.block_record(block.header_hash)
            if block_record.sub_epoch_summary_included is not None:
                if self.weight_proof_handler is not None:
                    await self.weight_proof_handler.create_prev_sub_epoch_segments()
        if advanced_peak:
            self._state_changed("new_peak")
            self.log.debug(
                f"Total time for {len(blocks_to_validate)} blocks: {time.time() - pre_validate_start}, "
                f"advanced: {advanced_peak}"
            )
        return True, advanced_peak, fork_height

    async def _finish_sync(self):
        """
        Finalize sync by setting sync mode to False, clearing all sync information, and adding any final
        blocks that we have finalized recently.
        """
        self.log.info("long sync done")
        self.sync_store.set_long_sync(False)
        self.sync_store.set_sync_mode(False)
        self._state_changed("sync_mode")
        if self.server is None:
            return None

        peak: Optional[BlockRecord] = self.blockchain.get_peak()
        async with self.blockchain.lock:
            await self.sync_store.clear_sync_info()

            peak_fb: FullBlock = await self.blockchain.get_full_peak()
            if peak is not None:
                await self.peak_post_processing(peak_fb, peak, peak.height - 1, None)

        if peak is not None and self.weight_proof_handler is not None:
            await self.weight_proof_handler.get_proof_of_weight(peak.header_hash)
            self._state_changed("block")

    def has_valid_pool_sig(self, block: Union[UnfinishedBlock, FullBlock]):
        if (
            block.foliage.foliage_block_data.pool_target
            == PoolTarget(self.constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH, uint32(0))
            and block.foliage.prev_block_hash != self.constants.GENESIS_CHALLENGE
            and block.reward_chain_block.proof_of_space.pool_public_key is not None
        ):
            if not AugSchemeMPL.verify(
                block.reward_chain_block.proof_of_space.pool_public_key,
                bytes(block.foliage.foliage_block_data.pool_target),
                block.foliage.foliage_block_data.pool_signature,
            ):
                return False
        return True

    async def signage_point_post_processing(
        self,
        request: full_node_protocol.RespondSignagePoint,
        peer: ws.WSChivesConnection,
        ip_sub_slot: Optional[EndOfSubSlotBundle],
    ):
        self.log.info(
            f"⏲️  Finished signage point {request.index_from_challenge}/"
            f"{self.constants.NUM_SPS_SUB_SLOT}: "
            f"CC: {request.challenge_chain_vdf.output.get_hash()} "
            f"RC: {request.reward_chain_vdf.output.get_hash()} "
        )
        self.signage_point_times[request.index_from_challenge] = time.time()
        sub_slot_tuple = self.full_node_store.get_sub_slot(request.challenge_chain_vdf.challenge)
        if sub_slot_tuple is not None:
            prev_challenge = sub_slot_tuple[0].challenge_chain.challenge_chain_end_of_slot_vdf.challenge
        else:
            prev_challenge = None

        # Notify nodes of the new signage point
        broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
            prev_challenge,
            request.challenge_chain_vdf.challenge,
            request.index_from_challenge,
            request.reward_chain_vdf.challenge,
        )
        msg = make_msg(ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot, broadcast)
        await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)

        peak = self.blockchain.get_peak()
        if peak is not None and peak.height > self.constants.MAX_SUB_SLOT_BLOCKS:
            sub_slot_iters = peak.sub_slot_iters
            difficulty = uint64(peak.weight - self.blockchain.block_record(peak.prev_hash).weight)
            # Makes sure to potentially update the difficulty if we are past the peak (into a new sub-slot)
            assert ip_sub_slot is not None
            if request.challenge_chain_vdf.challenge != ip_sub_slot.challenge_chain.get_hash():
                next_difficulty = self.blockchain.get_next_difficulty(peak.header_hash, True)
                next_sub_slot_iters = self.blockchain.get_next_slot_iters(peak.header_hash, True)
                difficulty = next_difficulty
                sub_slot_iters = next_sub_slot_iters
        else:
            difficulty = self.constants.DIFFICULTY_STARTING
            sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING

        # Notify farmers of the new signage point
        broadcast_farmer = farmer_protocol.NewSignagePoint(
            request.challenge_chain_vdf.challenge,
            request.challenge_chain_vdf.output.get_hash(),
            request.reward_chain_vdf.output.get_hash(),
            difficulty,
            sub_slot_iters,
            request.index_from_challenge,
        )
        msg = make_msg(ProtocolMessageTypes.new_signage_point, broadcast_farmer)
        await self.server.send_to_all([msg], NodeType.FARMER)

    async def peak_post_processing(
        self, block: FullBlock, record: BlockRecord, fork_height: uint32, peer: Optional[ws.WSChivesConnection]
    ):
        """
        Must be called under self.blockchain.lock. This updates the internal state of the full node with the
        latest peak information. It also notifies peers about the new peak.
        """
        difficulty = self.blockchain.get_next_difficulty(record.header_hash, False)
        sub_slot_iters = self.blockchain.get_next_slot_iters(record.header_hash, False)

        self.log.info(
            f"🌱 Updated peak to height {record.height}, weight {record.weight}, "
            f"hh {record.header_hash}, "
            f"forked at {fork_height}, rh: {record.reward_infusion_new_challenge}, "
            f"total iters: {record.total_iters}, "
            f"overflow: {record.overflow}, "
            f"deficit: {record.deficit}, "
            f"difficulty: {difficulty}, "
            f"sub slot iters: {sub_slot_iters}, "
            f"Generator size: "
            f"{len(bytes(block.transactions_generator)) if  block.transactions_generator else 'No tx'}, "
            f"Generator ref list size: "
            f"{len(block.transactions_generator_ref_list) if block.transactions_generator else 'No tx'}"
        )

        sub_slots = await self.blockchain.get_sp_and_ip_sub_slots(record.header_hash)
        assert sub_slots is not None

        if not self.sync_store.get_sync_mode():
            self.blockchain.clean_block_records()

        fork_block: Optional[BlockRecord] = None
        if fork_height != block.height - 1 and block.height != 0:
            # This is a reorg
            fork_block = self.blockchain.block_record(self.blockchain.height_to_hash(fork_height))

        added_eos, new_sps, new_ips = self.full_node_store.new_peak(
            record,
            block,
            sub_slots[0],
            sub_slots[1],
            fork_block,
            self.blockchain,
        )
        if sub_slots[1] is None:
            assert record.ip_sub_slot_total_iters(self.constants) == 0
        # Ensure the signage point is also in the store, for consistency
        self.full_node_store.new_signage_point(
            record.signage_point_index,
            self.blockchain,
            record,
            record.sub_slot_iters,
            SignagePoint(
                block.reward_chain_block.challenge_chain_sp_vdf,
                block.challenge_chain_sp_proof,
                block.reward_chain_block.reward_chain_sp_vdf,
                block.reward_chain_sp_proof,
            ),
            skip_vdf_validation=True,
        )

        # Update the mempool (returns successful pending transactions added to the mempool)
        for bundle, result, spend_name in await self.mempool_manager.new_peak(self.blockchain.get_peak()):
            self.log.debug(f"Added transaction to mempool: {spend_name}")
            mempool_item = self.mempool_manager.get_mempool_item(spend_name)
            assert mempool_item is not None
            fees = mempool_item.fee
            assert fees >= 0
            assert mempool_item.cost is not None
            new_tx = full_node_protocol.NewTransaction(
                spend_name,
                mempool_item.cost,
                uint64(bundle.fees()),
            )
            msg = make_msg(ProtocolMessageTypes.new_transaction, new_tx)
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

        # If there were pending end of slots that happen after this peak, broadcast them if they are added
        if added_eos is not None:
            broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                added_eos.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                added_eos.challenge_chain.get_hash(),
                uint8(0),
                added_eos.reward_chain.end_of_slot_vdf.challenge,
            )
            msg = make_msg(ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot, broadcast)
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

        if new_sps is not None and peer is not None:
            for index, sp in new_sps:
                assert (
                    sp.cc_vdf is not None
                    and sp.cc_proof is not None
                    and sp.rc_vdf is not None
                    and sp.rc_proof is not None
                )
                await self.signage_point_post_processing(
                    RespondSignagePoint(index, sp.cc_vdf, sp.cc_proof, sp.rc_vdf, sp.rc_proof), peer, sub_slots[1]
                )

        # TODO: maybe add and broadcast new IPs as well

        if record.height % 1000 == 0:
            # Occasionally clear data in full node store to keep memory usage small
            self.full_node_store.clear_seen_unfinished_blocks()
            self.full_node_store.clear_old_cache_entries()

        if self.sync_store.get_sync_mode() is False:
            await self.send_peak_to_timelords(block)

            # Tell full nodes about the new peak
            msg = make_msg(
                ProtocolMessageTypes.new_peak,
                full_node_protocol.NewPeak(
                    record.header_hash,
                    record.height,
                    record.weight,
                    fork_height,
                    block.reward_chain_block.get_unfinished().get_hash(),
                ),
            )
            if peer is not None:
                await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)
            else:
                await self.server.send_to_all([msg], NodeType.FULL_NODE)

        # Tell wallets about the new peak
        msg = make_msg(
            ProtocolMessageTypes.new_peak_wallet,
            wallet_protocol.NewPeakWallet(
                record.header_hash,
                record.height,
                record.weight,
                fork_height,
            ),
        )
        await self.server.send_to_all([msg], NodeType.WALLET)

        # Check if we detected a spent transaction, to load up our generator cache
        if block.transactions_generator is not None and self.full_node_store.previous_generator is None:
            generator_arg = detect_potential_template_generator(block.height, block.transactions_generator)
            if generator_arg:
                self.log.info(f"Saving previous generator for height {block.height}")
                self.full_node_store.previous_generator = generator_arg

        self._state_changed("new_peak")

    async def respond_block(
        self,
        respond_block: full_node_protocol.RespondBlock,
        peer: Optional[ws.WSChivesConnection] = None,
    ) -> Optional[Message]:
        """
        Receive a full block from a peer full node (or ourselves).
        """
        block: FullBlock = respond_block.block
        if self.sync_store.get_sync_mode():
            self.log.warning("self.sync_store.get_sync_mode() CODE:FULL_NODE.PY")
            return None

        # Adds the block to seen, and check if it's seen before (which means header is in memory)
        header_hash = block.header_hash
        if self.blockchain.contains_block(header_hash):
            self.log.warning("self.blockchain.contains_block(header_hash)")
            return None

        pre_validation_result: Optional[PreValidationResult] = None
        if (
            block.is_transaction_block()
            and block.transactions_info is not None
            and block.transactions_info.generator_root != bytes([0] * 32)
            and block.transactions_generator is None
        ):
            self.log.warning("This is the case where we already had the unfinished block, and asked for this block without")
            # This is the case where we already had the unfinished block, and asked for this block without
            # the transactions (since we already had them). Therefore, here we add the transactions.
            unfinished_rh: bytes32 = block.reward_chain_block.get_unfinished().get_hash()
            unf_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(unfinished_rh)
            if (
                unf_block is not None
                and unf_block.transactions_generator is not None
                and unf_block.foliage_transaction_block == block.foliage_transaction_block
            ):
                self.log.warning("pre_validation_result = self.full_node_store.get_unfinished_block_result(unfinished_rh)")
                pre_validation_result = self.full_node_store.get_unfinished_block_result(unfinished_rh)
                assert pre_validation_result is not None
                block = dataclasses.replace(
                    block,
                    transactions_generator=unf_block.transactions_generator,
                    transactions_generator_ref_list=unf_block.transactions_generator_ref_list,
                )
            else:
                self.log.warning("We still do not have the correct information for this block, perhaps there is a duplicate block")
                # We still do not have the correct information for this block, perhaps there is a duplicate block
                # with the same unfinished block hash in the cache, so we need to fetch the correct one
                if peer is None:
                    return None

                block_response: Optional[Any] = await peer.request_block(
                    full_node_protocol.RequestBlock(block.height, True)
                )
                if block_response is None or not isinstance(block_response, full_node_protocol.RespondBlock):
                    self.log.warning(
                        f"Was not able to fetch the correct block for height {block.height} {block_response}"
                    )
                    return None
                new_block: FullBlock = block_response.block
                if new_block.foliage_transaction_block != block.foliage_transaction_block:
                    self.log.warning(f"Received the wrong block for height {block.height} {new_block.header_hash}")
                    return None
                assert new_block.transactions_generator is not None

                self.log.debug(
                    f"Wrong info in the cache for bh {new_block.header_hash}, there might be multiple blocks from the "
                    f"same farmer with the same pospace."
                )
                # This recursion ends here, we cannot recurse again because transactions_generator is not None
                return await self.respond_block(block_response, peer)

        async with self.blockchain.lock:
            # self.log.warning("After acquiring the lock, check again, because another asyncio thread might have added it")
            # self.log.warning(self.blockchain.contains_block(header_hash))
            # After acquiring the lock, check again, because another asyncio thread might have added it
            if self.blockchain.contains_block(header_hash):
                self.log.warning("self.blockchain.contains_block(header_hash) 1199")
                return None
            validation_start = time.time()
            # Tries to add the block to the blockchain, if we already validated transactions, don't do it again
            npc_results = {}
            # self.log.warning("if pre_validation_result is not None and pre_validation_result.npc_result is not None:")
            # self.log.warning(pre_validation_result is not None)
            if pre_validation_result is not None and pre_validation_result.npc_result is not None:
                npc_results[block.height] = pre_validation_result.npc_result
            pre_validation_results: Optional[
                List[PreValidationResult]
            ] = await self.blockchain.pre_validate_blocks_multiprocessing([block], npc_results)
            # self.log.warning("if pre_validation_results is None:")
            if pre_validation_results is None:
                raise ValueError(f"Failed to validate block {header_hash} height {block.height}")
            if pre_validation_results[0].error is not None:
                if Err(pre_validation_results[0].error) == Err.INVALID_PREV_BLOCK_HASH:
                    added: ReceiveBlockResult = ReceiveBlockResult.DISCONNECTED_BLOCK
                    error_code: Optional[Err] = Err.INVALID_PREV_BLOCK_HASH
                    fork_height: Optional[uint32] = None
                    self.log.warning("error_code: Optional[Err] = Err.INVALID_PREV_BLOCK_HASH")
                else:
                    self.log.warning("Failed to validate block")
                    raise ValueError(
                        f"Failed to validate block {header_hash} height "
                        f"{block.height}: {Err(pre_validation_results[0].error).name}"
                    )
            else:
                result_to_validate = (
                    pre_validation_results[0] if pre_validation_result is None else pre_validation_result
                )
                # self.log.warning("assert result_to_validate.required_iters == pre_validation_results[0].required_iters")
                assert result_to_validate.required_iters == pre_validation_results[0].required_iters
                added, error_code, fork_height = await self.blockchain.receive_block(block, result_to_validate, None)
                if (
                    self.full_node_store.previous_generator is not None
                    and fork_height is not None
                    and fork_height < self.full_node_store.previous_generator.block_height
                ):
                    self.full_node_store.previous_generator = None
                    # self.log.warning("self.full_node_store.previous_generator = None")
            validation_time = time.time() - validation_start
            # self.log.warning("if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:")
            if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
                self.log.warning("added == ReceiveBlockResult.ALREADY_HAVE_BLOCK: 1238")
                return None
            elif added == ReceiveBlockResult.INVALID_BLOCK:
                assert error_code is not None
                self.log.error(f"Block {header_hash} at height {block.height} is invalid with code {error_code}.")
                raise ConsensusError(error_code, header_hash)

            elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
                self.log.info(f"Disconnected block {header_hash} at height {block.height}")
                return None
            elif added == ReceiveBlockResult.NEW_PEAK:
                # self.log.warning("added == ReceiveBlockResult.NEW_PEAK: 1249")
                # Only propagate blocks which extend the blockchain (becomes one of the heads)
                new_peak: Optional[BlockRecord] = self.blockchain.get_peak()
                assert new_peak is not None and fork_height is not None

                await self.peak_post_processing(block, new_peak, fork_height, peer)

            elif added == ReceiveBlockResult.ADDED_AS_ORPHAN:
                self.log.info(
                    f"Received orphan block of height {block.height} rh " f"{block.reward_chain_block.get_hash()}"
                )
            else:
                self.log.warning("# Should never reach here, all the cases are covered 1261")
                # Should never reach here, all the cases are covered
                raise RuntimeError(f"Invalid result from receive_block {added}")
        percent_full_str = (
            (
                ", percent full: "
                + str(round(100.0 * float(block.transactions_info.cost) / self.constants.MAX_BLOCK_COST_CLVM, 3))
                + "%"
            )
            if block.transactions_info is not None
            else ""
        )
        self.log.info(
            f"Block validation time: {validation_time}, "
            f"cost: {block.transactions_info.cost if block.transactions_info is not None else 'None'}"
            f"{percent_full_str}"
        )

        # This code path is reached if added == ADDED_AS_ORPHAN or NEW_TIP
        peak = self.blockchain.get_peak()
        assert peak is not None

        # Removes all temporary data for old blocks
        clear_height = uint32(max(0, peak.height - 50))
        self.full_node_store.clear_candidate_blocks_below(clear_height)
        self.full_node_store.clear_unfinished_blocks_below(clear_height)
        if peak.height % 1000 == 0 and not self.sync_store.get_sync_mode():
            await self.sync_store.clear_sync_info()  # Occasionally clear sync peer info
        self._state_changed("block")
        record = self.blockchain.block_record(block.header_hash)
        if self.weight_proof_handler is not None and record.sub_epoch_summary_included is not None:
            if self._segment_task is None or self._segment_task.done():
                self._segment_task = asyncio.create_task(self.weight_proof_handler.create_prev_sub_epoch_segments())
        return None

    async def respond_unfinished_block(
        self,
        respond_unfinished_block: full_node_protocol.RespondUnfinishedBlock,
        peer: Optional[ws.WSChivesConnection],
        farmed_block: bool = False,
    ):
        """
        We have received an unfinished block, either created by us, or from another peer.
        We can validate it and if it's a good block, propagate it to other peers and
        timelords.
        """
        block = respond_unfinished_block.unfinished_block

        if block.prev_header_hash != self.constants.GENESIS_CHALLENGE and not self.blockchain.contains_block(
            block.prev_header_hash
        ):
            # No need to request the parent, since the peer will send it to us anyway, via NewPeak
            self.log.debug("Received a disconnected unfinished block")
            return None

        # Adds the unfinished block to seen, and check if it's seen before, to prevent
        # processing it twice. This searches for the exact version of the unfinished block (there can be many different
        # foliages for the same trunk). This is intentional, to prevent DOS attacks.
        # Note that it does not require that this block was successfully processed
        if self.full_node_store.seen_unfinished_block(block.get_hash()):
            return None

        block_hash = block.reward_chain_block.get_hash()

        # This searched for the trunk hash (unfinished reward hash). If we have already added a block with the same
        # hash, return
        if self.full_node_store.get_unfinished_block(block_hash) is not None:
            return None

        peak: Optional[BlockRecord] = self.blockchain.get_peak()
        if peak is not None:
            if block.total_iters < peak.sp_total_iters(self.constants):
                # This means this unfinished block is pretty far behind, it will not add weight to our chain
                return None

        if block.prev_header_hash == self.constants.GENESIS_CHALLENGE:
            prev_b = None
        else:
            prev_b = self.blockchain.block_record(block.prev_header_hash)

        # Count the blocks in sub slot, and check if it's a new epoch
        if len(block.finished_sub_slots) > 0:
            num_blocks_in_ss = 1  # Curr
        else:
            curr = self.blockchain.try_block_record(block.prev_header_hash)
            num_blocks_in_ss = 2  # Curr and prev
            while (curr is not None) and not curr.first_in_sub_slot:
                curr = self.blockchain.try_block_record(curr.prev_hash)
                num_blocks_in_ss += 1

        if num_blocks_in_ss > self.constants.MAX_SUB_SLOT_BLOCKS:
            # TODO: potentially allow overflow blocks here, which count for the next slot
            self.log.warning("Too many blocks added, not adding block")
            return None

        async with self.blockchain.lock:
            # TODO: pre-validate VDFs outside of lock
            validation_start = time.time()
            validate_result = await self.blockchain.validate_unfinished_block(block)
            if validate_result.error is not None:
                if validate_result.error == Err.COIN_AMOUNT_NEGATIVE.value:
                    # TODO: remove in the future, hotfix for 1.1.5 peers to not disconnect older peers
                    self.log.info(f"Consensus error {validate_result.error}, not disconnecting")
                    return
                raise ConsensusError(Err(validate_result.error))
            validation_time = time.time() - validation_start

        assert validate_result.required_iters is not None

        # Perform another check, in case we have already concurrently added the same unfinished block
        if self.full_node_store.get_unfinished_block(block_hash) is not None:
            return None

        if block.prev_header_hash == self.constants.GENESIS_CHALLENGE:
            height = uint32(0)
        else:
            height = uint32(self.blockchain.block_record(block.prev_header_hash).height + 1)

        ses: Optional[SubEpochSummary] = next_sub_epoch_summary(
            self.constants,
            self.blockchain,
            validate_result.required_iters,
            block,
            True,
        )

        self.full_node_store.add_unfinished_block(height, block, validate_result)
        if farmed_block is True:
            self.log.info(
                f"🍀 ️Farmed unfinished_block {block_hash}, SP: {block.reward_chain_block.signage_point_index}, "
                f"validation time: {validation_time}, "
                f"cost: {block.transactions_info.cost if block.transactions_info else 'None'}"
            )
        else:
            percent_full_str = (
                (
                    ", percent full: "
                    + str(round(100.0 * float(block.transactions_info.cost) / self.constants.MAX_BLOCK_COST_CLVM, 3))
                    + "%"
                )
                if block.transactions_info is not None
                else ""
            )
            self.log.info(
                f"Added unfinished_block {block_hash}, not farmed by us,"
                f" SP: {block.reward_chain_block.signage_point_index} farmer response time: "
                f"{time.time() - self.signage_point_times[block.reward_chain_block.signage_point_index]}, "
                f"Pool pk {encode_puzzle_hash(block.foliage.foliage_block_data.pool_target.puzzle_hash, 'xcc')}, "
                f"validation time: {validation_time}, "
                f"cost: {block.transactions_info.cost if block.transactions_info else 'None'}"
                f"{percent_full_str}"
            )

        sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
            self.constants,
            len(block.finished_sub_slots) > 0,
            prev_b,
            self.blockchain,
        )

        if block.reward_chain_block.signage_point_index == 0:
            res = self.full_node_store.get_sub_slot(block.reward_chain_block.pos_ss_cc_challenge_hash)
            if res is None:
                if block.reward_chain_block.pos_ss_cc_challenge_hash == self.constants.GENESIS_CHALLENGE:
                    rc_prev = self.constants.GENESIS_CHALLENGE
                else:
                    self.log.warning(f"Do not have sub slot {block.reward_chain_block.pos_ss_cc_challenge_hash}")
                    return None
            else:
                rc_prev = res[0].reward_chain.get_hash()
        else:
            assert block.reward_chain_block.reward_chain_sp_vdf is not None
            rc_prev = block.reward_chain_block.reward_chain_sp_vdf.challenge

        timelord_request = timelord_protocol.NewUnfinishedBlockTimelord(
            block.reward_chain_block,
            difficulty,
            sub_slot_iters,
            block.foliage,
            ses,
            rc_prev,
        )

        timelord_msg = make_msg(ProtocolMessageTypes.new_unfinished_block_timelord, timelord_request)
        await self.server.send_to_all([timelord_msg], NodeType.TIMELORD)

        full_node_request = full_node_protocol.NewUnfinishedBlock(block.reward_chain_block.get_hash())
        msg = make_msg(ProtocolMessageTypes.new_unfinished_block, full_node_request)
        if peer is not None:
            await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)
        else:
            await self.server.send_to_all([msg], NodeType.FULL_NODE)
        self._state_changed("unfinished_block")

    async def new_infusion_point_vdf(
        self, request: timelord_protocol.NewInfusionPointVDF, timelord_peer: Optional[ws.WSChivesConnection] = None
    ) -> Optional[Message]:
        # Lookup unfinished blocks
        unfinished_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(
            request.unfinished_reward_hash
        )

        if unfinished_block is None:
            self.log.warning(
                f"Do not have unfinished reward chain block {request.unfinished_reward_hash}, cannot finish."
            )
            return None

        prev_b: Optional[BlockRecord] = None

        target_rc_hash = request.reward_chain_ip_vdf.challenge
        last_slot_cc_hash = request.challenge_chain_ip_vdf.challenge

        # Backtracks through end of slot objects, should work for multiple empty sub slots
        for eos, _, _ in reversed(self.full_node_store.finished_sub_slots):
            if eos is not None and eos.reward_chain.get_hash() == target_rc_hash:
                target_rc_hash = eos.reward_chain.end_of_slot_vdf.challenge
        if target_rc_hash == self.constants.GENESIS_CHALLENGE:
            prev_b = None
        else:
            # Find the prev block, starts looking backwards from the peak. target_rc_hash must be the hash of a block
            # and not an end of slot (since we just looked through the slots and backtracked)
            curr: Optional[BlockRecord] = self.blockchain.get_peak()

            for _ in range(10):
                if curr is None:
                    break
                if curr.reward_infusion_new_challenge == target_rc_hash:
                    # Found our prev block
                    prev_b = curr
                    break
                curr = self.blockchain.try_block_record(curr.prev_hash)

            # If not found, cache keyed on prev block
            if prev_b is None:
                self.full_node_store.add_to_future_ip(request)
                self.log.warning(f"Previous block is None, infusion point {request.reward_chain_ip_vdf.challenge}")
                return None

        finished_sub_slots: Optional[List[EndOfSubSlotBundle]] = self.full_node_store.get_finished_sub_slots(
            self.blockchain,
            prev_b,
            last_slot_cc_hash,
        )
        if finished_sub_slots is None:
            return None

        sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
            self.constants,
            len(finished_sub_slots) > 0,
            prev_b,
            self.blockchain,
        )

        if unfinished_block.reward_chain_block.pos_ss_cc_challenge_hash == self.constants.GENESIS_CHALLENGE:
            sub_slot_start_iters = uint128(0)
        else:
            ss_res = self.full_node_store.get_sub_slot(unfinished_block.reward_chain_block.pos_ss_cc_challenge_hash)
            if ss_res is None:
                self.log.warning(f"Do not have sub slot {unfinished_block.reward_chain_block.pos_ss_cc_challenge_hash}")
                return None
            _, _, sub_slot_start_iters = ss_res
        sp_total_iters = uint128(
            sub_slot_start_iters
            + calculate_sp_iters(
                self.constants,
                sub_slot_iters,
                unfinished_block.reward_chain_block.signage_point_index,
            )
        )

        block: FullBlock = unfinished_block_to_full_block(
            unfinished_block,
            request.challenge_chain_ip_vdf,
            request.challenge_chain_ip_proof,
            request.reward_chain_ip_vdf,
            request.reward_chain_ip_proof,
            request.infused_challenge_chain_ip_vdf,
            request.infused_challenge_chain_ip_proof,
            finished_sub_slots,
            prev_b,
            self.blockchain,
            sp_total_iters,
            difficulty,
        )
        if not self.has_valid_pool_sig(block):
            self.log.warning("Trying to make a pre-farm block but height is not 0")
            return None
        try:
            RespondBlock_FullNode = full_node_protocol.RespondBlock(block)
            # self.log.warning(RespondBlock_FullNode)
            await self.respond_block(RespondBlock_FullNode)
        except Exception as e:
            self.log.warning(f"Consensus error validating block: {e}")
            if timelord_peer is not None:
                # Only sends to the timelord who sent us this VDF, to reset them to the correct peak
                await self.send_peak_to_timelords(peer=timelord_peer)
        return None

    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: ws.WSChivesConnection
    ) -> Tuple[Optional[Message], bool]:

        fetched_ss = self.full_node_store.get_sub_slot(request.end_of_slot_bundle.challenge_chain.get_hash())
        if fetched_ss is not None:
            # Already have the sub-slot
            return None, True

        async with self.timelord_lock:
            fetched_ss = self.full_node_store.get_sub_slot(
                request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            )
            if (
                (fetched_ss is None)
                and request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
                != self.constants.GENESIS_CHALLENGE
            ):
                # If we don't have the prev, request the prev instead
                full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
                    request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                    uint8(0),
                    bytes([0] * 32),
                )
                return (
                    make_msg(ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot, full_node_request),
                    False,
                )

            peak = self.blockchain.get_peak()
            if peak is not None and peak.height > 2:
                next_sub_slot_iters = self.blockchain.get_next_slot_iters(peak.header_hash, True)
                next_difficulty = self.blockchain.get_next_difficulty(peak.header_hash, True)
            else:
                next_sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING
                next_difficulty = self.constants.DIFFICULTY_STARTING

            # Adds the sub slot and potentially get new infusions
            new_infusions = self.full_node_store.new_finished_sub_slot(
                request.end_of_slot_bundle,
                self.blockchain,
                peak,
                await self.blockchain.get_full_peak(),
            )
            # It may be an empty list, even if it's not None. Not None means added successfully
            if new_infusions is not None:
                self.log.info(
                    f"⏲️  Finished sub slot, SP {self.constants.NUM_SPS_SUB_SLOT}/{self.constants.NUM_SPS_SUB_SLOT}, "
                    f"{request.end_of_slot_bundle.challenge_chain.get_hash()}, "
                    f"number of sub-slots: {len(self.full_node_store.finished_sub_slots)}, "
                    f"RC hash: {request.end_of_slot_bundle.reward_chain.get_hash()}, "
                    f"Deficit {request.end_of_slot_bundle.reward_chain.deficit}"
                )
                # Notify full nodes of the new sub-slot
                broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                    request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                    request.end_of_slot_bundle.challenge_chain.get_hash(),
                    uint8(0),
                    request.end_of_slot_bundle.reward_chain.end_of_slot_vdf.challenge,
                )
                msg = make_msg(ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot, broadcast)
                await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)

                for infusion in new_infusions:
                    await self.new_infusion_point_vdf(infusion)

                # Notify farmers of the new sub-slot
                broadcast_farmer = farmer_protocol.NewSignagePoint(
                    request.end_of_slot_bundle.challenge_chain.get_hash(),
                    request.end_of_slot_bundle.challenge_chain.get_hash(),
                    request.end_of_slot_bundle.reward_chain.get_hash(),
                    next_difficulty,
                    next_sub_slot_iters,
                    uint8(0),
                )
                msg = make_msg(ProtocolMessageTypes.new_signage_point, broadcast_farmer)
                await self.server.send_to_all([msg], NodeType.FARMER)
                return None, True
            else:
                self.log.info(
                    f"End of slot not added CC challenge "
                    f"{request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge}"
                )
        return None, False

    async def respond_transaction(
        self,
        transaction: SpendBundle,
        spend_name: bytes32,
        peer: Optional[ws.WSChivesConnection] = None,
        test: bool = False,
    ) -> Tuple[MempoolInclusionStatus, Optional[Err]]:
        if self.sync_store.get_sync_mode():
            return MempoolInclusionStatus.FAILED, Err.NO_TRANSACTIONS_WHILE_SYNCING
        if not test and not (await self.synced()):
            return MempoolInclusionStatus.FAILED, Err.NO_TRANSACTIONS_WHILE_SYNCING

        # No transactions in mempool in initial client. Remove 6 weeks after launch
        if int(time.time()) <= self.constants.INITIAL_FREEZE_END_TIMESTAMP:
            return MempoolInclusionStatus.FAILED, Err.INITIAL_TRANSACTION_FREEZE

        if self.mempool_manager.seen(spend_name):
            return MempoolInclusionStatus.FAILED, Err.ALREADY_INCLUDING_TRANSACTION
        self.mempool_manager.add_and_maybe_pop_seen(spend_name)
        self.log.debug(f"Processing transaction: {spend_name}")
        # Ignore if syncing
        if self.sync_store.get_sync_mode():
            status = MempoolInclusionStatus.FAILED
            error: Optional[Err] = Err.NO_TRANSACTIONS_WHILE_SYNCING
            self.mempool_manager.remove_seen(spend_name)
        else:
            try:
                cost_result = await self.mempool_manager.pre_validate_spendbundle(transaction)
            except Exception as e:
                self.mempool_manager.remove_seen(spend_name)
                raise e
            async with self.mempool_manager.lock:
                if self.mempool_manager.get_spendbundle(spend_name) is not None:
                    self.mempool_manager.remove_seen(spend_name)
                    return MempoolInclusionStatus.FAILED, Err.ALREADY_INCLUDING_TRANSACTION
                cost, status, error = await self.mempool_manager.add_spendbundle(transaction, cost_result, spend_name)
            if status == MempoolInclusionStatus.SUCCESS:
                self.log.debug(
                    f"Added transaction to mempool: {spend_name} mempool size: "
                    f"{self.mempool_manager.mempool.total_mempool_cost}"
                )
                # Only broadcast successful transactions, not pending ones. Otherwise it's a DOS
                # vector.
                mempool_item = self.mempool_manager.get_mempool_item(spend_name)
                assert mempool_item is not None
                fees = mempool_item.fee
                assert fees >= 0
                assert cost is not None
                new_tx = full_node_protocol.NewTransaction(
                    spend_name,
                    cost,
                    fees,
                )
                msg = make_msg(ProtocolMessageTypes.new_transaction, new_tx)
                if peer is None:
                    await self.server.send_to_all([msg], NodeType.FULL_NODE)
                else:
                    await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)
            else:
                self.mempool_manager.remove_seen(spend_name)
                self.log.debug(
                    f"Wasn't able to add transaction with id {spend_name}, " f"status {status} error: {error}"
                )
        return status, error

    async def _needs_compact_proof(
        self, vdf_info: VDFInfo, header_block: HeaderBlock, field_vdf: CompressibleVDFField
    ) -> bool:
        if field_vdf == CompressibleVDFField.CC_EOS_VDF:
            for sub_slot in header_block.finished_sub_slots:
                if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf == vdf_info:
                    if (
                        sub_slot.proofs.challenge_chain_slot_proof.witness_type == 0
                        and sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity
                    ):
                        return False
                    return True
        if field_vdf == CompressibleVDFField.ICC_EOS_VDF:
            for sub_slot in header_block.finished_sub_slots:
                if (
                    sub_slot.infused_challenge_chain is not None
                    and sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf == vdf_info
                ):
                    assert sub_slot.proofs.infused_challenge_chain_slot_proof is not None
                    if (
                        sub_slot.proofs.infused_challenge_chain_slot_proof.witness_type == 0
                        and sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
                    ):
                        return False
                    return True
        if field_vdf == CompressibleVDFField.CC_SP_VDF:
            if header_block.reward_chain_block.challenge_chain_sp_vdf is None:
                return False
            if vdf_info == header_block.reward_chain_block.challenge_chain_sp_vdf:
                assert header_block.challenge_chain_sp_proof is not None
                if (
                    header_block.challenge_chain_sp_proof.witness_type == 0
                    and header_block.challenge_chain_sp_proof.normalized_to_identity
                ):
                    return False
                return True
        if field_vdf == CompressibleVDFField.CC_IP_VDF:
            if vdf_info == header_block.reward_chain_block.challenge_chain_ip_vdf:
                if (
                    header_block.challenge_chain_ip_proof.witness_type == 0
                    and header_block.challenge_chain_ip_proof.normalized_to_identity
                ):
                    return False
                return True
        return False

    async def _can_accept_compact_proof(
        self,
        vdf_info: VDFInfo,
        vdf_proof: VDFProof,
        height: uint32,
        header_hash: bytes32,
        field_vdf: CompressibleVDFField,
    ) -> bool:
        """
        - Checks if the provided proof is indeed compact.
        - Checks if proof verifies given the vdf_info from the start of sub-slot.
        - Checks if the provided vdf_info is correct, assuming it refers to the start of sub-slot.
        - Checks if the existing proof was non-compact. Ignore this proof if we already have a compact proof.
        """
        is_fully_compactified = await self.block_store.is_fully_compactified(header_hash)
        if is_fully_compactified is None or is_fully_compactified:
            self.log.info(f"Already compactified block: {header_hash}. Ignoring.")
            return False
        if vdf_proof.witness_type > 0 or not vdf_proof.normalized_to_identity:
            self.log.error(f"Received vdf proof is not compact: {vdf_proof}.")
            return False
        if not vdf_proof.is_valid(self.constants, ClassgroupElement.get_default_element(), vdf_info):
            self.log.error(f"Received compact vdf proof is not valid: {vdf_proof}.")
            return False
        header_block = await self.blockchain.get_header_block_by_height(height, header_hash, tx_filter=False)
        if header_block is None:
            self.log.error(f"Can't find block for given compact vdf. Height: {height} Header hash: {header_hash}")
            return False
        is_new_proof = await self._needs_compact_proof(vdf_info, header_block, field_vdf)
        if not is_new_proof:
            self.log.info(f"Duplicate compact proof. Height: {height}. Header hash: {header_hash}.")
        return is_new_proof

    async def _replace_proof(
        self,
        vdf_info: VDFInfo,
        vdf_proof: VDFProof,
        height: uint32,
        field_vdf: CompressibleVDFField,
    ) -> bool:
        full_blocks = await self.block_store.get_full_blocks_at([height])
        assert len(full_blocks) > 0
        replaced = False
        for block in full_blocks:
            new_block = None
            block_record = await self.blockchain.get_block_record_from_db(self.blockchain.height_to_hash(height))
            assert block_record is not None

            if field_vdf == CompressibleVDFField.CC_EOS_VDF:
                for index, sub_slot in enumerate(block.finished_sub_slots):
                    if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf == vdf_info:
                        new_proofs = dataclasses.replace(sub_slot.proofs, challenge_chain_slot_proof=vdf_proof)
                        new_subslot = dataclasses.replace(sub_slot, proofs=new_proofs)
                        new_finished_subslots = block.finished_sub_slots
                        new_finished_subslots[index] = new_subslot
                        new_block = dataclasses.replace(block, finished_sub_slots=new_finished_subslots)
                        break
            if field_vdf == CompressibleVDFField.ICC_EOS_VDF:
                for index, sub_slot in enumerate(block.finished_sub_slots):
                    if (
                        sub_slot.infused_challenge_chain is not None
                        and sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf == vdf_info
                    ):
                        new_proofs = dataclasses.replace(sub_slot.proofs, infused_challenge_chain_slot_proof=vdf_proof)
                        new_subslot = dataclasses.replace(sub_slot, proofs=new_proofs)
                        new_finished_subslots = block.finished_sub_slots
                        new_finished_subslots[index] = new_subslot
                        new_block = dataclasses.replace(block, finished_sub_slots=new_finished_subslots)
                        break
            if field_vdf == CompressibleVDFField.CC_SP_VDF:
                if block.reward_chain_block.challenge_chain_sp_vdf == vdf_info:
                    assert block.challenge_chain_sp_proof is not None
                    new_block = dataclasses.replace(block, challenge_chain_sp_proof=vdf_proof)
            if field_vdf == CompressibleVDFField.CC_IP_VDF:
                if block.reward_chain_block.challenge_chain_ip_vdf == vdf_info:
                    new_block = dataclasses.replace(block, challenge_chain_ip_proof=vdf_proof)
            if new_block is None:
                continue
            async with self.db_wrapper.lock:
                await self.block_store.add_full_block(new_block.header_hash, new_block, block_record)
                await self.block_store.db_wrapper.commit_transaction()
                replaced = True
        return replaced

    async def respond_compact_proof_of_time(self, request: timelord_protocol.RespondCompactProofOfTime):
        field_vdf = CompressibleVDFField(int(request.field_vdf))
        if not await self._can_accept_compact_proof(
            request.vdf_info, request.vdf_proof, request.height, request.header_hash, field_vdf
        ):
            return None
        async with self.blockchain.compact_proof_lock:
            replaced = await self._replace_proof(request.vdf_info, request.vdf_proof, request.height, field_vdf)
        if not replaced:
            self.log.error(f"Could not replace compact proof: {request.height}")
            return None
        msg = make_msg(
            ProtocolMessageTypes.new_compact_vdf,
            full_node_protocol.NewCompactVDF(request.height, request.header_hash, request.field_vdf, request.vdf_info),
        )
        if self.server is not None:
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

    async def new_compact_vdf(self, request: full_node_protocol.NewCompactVDF, peer: ws.WSChivesConnection):
        is_fully_compactified = await self.block_store.is_fully_compactified(request.header_hash)
        if is_fully_compactified is None or is_fully_compactified:
            return False
        header_block = await self.blockchain.get_header_block_by_height(
            request.height, request.header_hash, tx_filter=False
        )
        if header_block is None:
            return None
        field_vdf = CompressibleVDFField(int(request.field_vdf))
        if await self._needs_compact_proof(request.vdf_info, header_block, field_vdf):
            peer_request = full_node_protocol.RequestCompactVDF(
                request.height, request.header_hash, request.field_vdf, request.vdf_info
            )
            response = await peer.request_compact_vdf(peer_request, timeout=10)
            if response is not None and isinstance(response, full_node_protocol.RespondCompactVDF):
                await self.respond_compact_vdf(response, peer)

    async def request_compact_vdf(self, request: full_node_protocol.RequestCompactVDF, peer: ws.WSChivesConnection):
        header_block = await self.blockchain.get_header_block_by_height(
            request.height, request.header_hash, tx_filter=False
        )
        if header_block is None:
            return None
        vdf_proof: Optional[VDFProof] = None
        field_vdf = CompressibleVDFField(int(request.field_vdf))
        if field_vdf == CompressibleVDFField.CC_EOS_VDF:
            for sub_slot in header_block.finished_sub_slots:
                if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf == request.vdf_info:
                    vdf_proof = sub_slot.proofs.challenge_chain_slot_proof
                    break
        if field_vdf == CompressibleVDFField.ICC_EOS_VDF:
            for sub_slot in header_block.finished_sub_slots:
                if (
                    sub_slot.infused_challenge_chain is not None
                    and sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf == request.vdf_info
                ):
                    vdf_proof = sub_slot.proofs.infused_challenge_chain_slot_proof
                    break
        if (
            field_vdf == CompressibleVDFField.CC_SP_VDF
            and header_block.reward_chain_block.challenge_chain_sp_vdf == request.vdf_info
        ):
            vdf_proof = header_block.challenge_chain_sp_proof
        if (
            field_vdf == CompressibleVDFField.CC_IP_VDF
            and header_block.reward_chain_block.challenge_chain_ip_vdf == request.vdf_info
        ):
            vdf_proof = header_block.challenge_chain_ip_proof
        if vdf_proof is None or vdf_proof.witness_type > 0 or not vdf_proof.normalized_to_identity:
            self.log.error(f"{peer} requested compact vdf we don't have, height: {request.height}.")
            return None
        compact_vdf = full_node_protocol.RespondCompactVDF(
            request.height,
            request.header_hash,
            request.field_vdf,
            request.vdf_info,
            vdf_proof,
        )
        msg = make_msg(ProtocolMessageTypes.respond_compact_vdf, compact_vdf)
        await peer.send_message(msg)

    async def respond_compact_vdf(self, request: full_node_protocol.RespondCompactVDF, peer: ws.WSChivesConnection):
        field_vdf = CompressibleVDFField(int(request.field_vdf))
        if not await self._can_accept_compact_proof(
            request.vdf_info, request.vdf_proof, request.height, request.header_hash, field_vdf
        ):
            return None
        async with self.blockchain.compact_proof_lock:
            if self.blockchain.seen_compact_proofs(request.vdf_info, request.height):
                return None
            replaced = await self._replace_proof(request.vdf_info, request.vdf_proof, request.height, field_vdf)
        if not replaced:
            self.log.error(f"Could not replace compact proof: {request.height}")
            return None
        msg = make_msg(
            ProtocolMessageTypes.new_compact_vdf,
            full_node_protocol.NewCompactVDF(request.height, request.header_hash, request.field_vdf, request.vdf_info),
        )
        if self.server is not None:
            await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)

    async def broadcast_uncompact_blocks(
        self, uncompact_interval_scan: int, target_uncompact_proofs: int, sanitize_weight_proof_only: bool
    ):
        min_height: Optional[int] = 0
        try:
            while not self._shut_down:
                while self.sync_store.get_sync_mode():
                    if self._shut_down:
                        return None
                    await asyncio.sleep(30)

                broadcast_list: List[timelord_protocol.RequestCompactProofOfTime] = []
                new_min_height = None
                max_height = self.blockchain.get_peak_height()
                if max_height is None:
                    await asyncio.sleep(30)
                    continue
                # Calculate 'min_height' correctly the first time this task is launched, using the db
                assert min_height is not None
                min_height = await self.block_store.get_first_not_compactified(min_height)
                if min_height is None or min_height > max(0, max_height - 1000):
                    min_height = max(0, max_height - 1000)
                batches_finished = 0
                self.log.info("Scanning the blockchain for uncompact blocks.")
                assert max_height is not None
                assert min_height is not None
                for h in range(min_height, max_height, 100):
                    # Got 10 times the target header count, sampling the target headers should contain
                    # enough randomness to split the work between blueboxes.
                    if len(broadcast_list) > target_uncompact_proofs * 10:
                        break
                    stop_height = min(h + 99, max_height)
                    assert min_height is not None
                    headers = await self.blockchain.get_header_blocks_in_range(min_height, stop_height, tx_filter=False)
                    records: Dict[bytes32, BlockRecord] = {}
                    if sanitize_weight_proof_only:
                        records = await self.blockchain.get_block_records_in_range(min_height, stop_height)
                    for header in headers.values():
                        prev_broadcast_list_len = len(broadcast_list)
                        expected_header_hash = self.blockchain.height_to_hash(header.height)
                        if header.header_hash != expected_header_hash:
                            continue
                        if sanitize_weight_proof_only:
                            assert header.header_hash in records
                            record = records[header.header_hash]
                        for sub_slot in header.finished_sub_slots:
                            if (
                                sub_slot.proofs.challenge_chain_slot_proof.witness_type > 0
                                or not sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity
                            ):
                                broadcast_list.append(
                                    timelord_protocol.RequestCompactProofOfTime(
                                        sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf,
                                        header.header_hash,
                                        header.height,
                                        uint8(CompressibleVDFField.CC_EOS_VDF),
                                    )
                                )
                            if sub_slot.proofs.infused_challenge_chain_slot_proof is not None and (
                                sub_slot.proofs.infused_challenge_chain_slot_proof.witness_type > 0
                                or not sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
                            ):
                                assert sub_slot.infused_challenge_chain is not None
                                broadcast_list.append(
                                    timelord_protocol.RequestCompactProofOfTime(
                                        sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf,
                                        header.header_hash,
                                        header.height,
                                        uint8(CompressibleVDFField.ICC_EOS_VDF),
                                    )
                                )
                        # Running in 'sanitize_weight_proof_only' ignores CC_SP_VDF and CC_IP_VDF
                        # unless this is a challenge block.
                        if sanitize_weight_proof_only:
                            if not record.is_challenge_block(self.constants):
                                # Calculates 'new_min_height' as described below.
                                if (
                                    prev_broadcast_list_len == 0
                                    and len(broadcast_list) > 0
                                    and h <= max(0, max_height - 1000)
                                ):
                                    new_min_height = header.height
                                # Skip calculations for CC_SP_VDF and CC_IP_VDF.
                                continue
                        if header.challenge_chain_sp_proof is not None and (
                            header.challenge_chain_sp_proof.witness_type > 0
                            or not header.challenge_chain_sp_proof.normalized_to_identity
                        ):
                            assert header.reward_chain_block.challenge_chain_sp_vdf is not None
                            broadcast_list.append(
                                timelord_protocol.RequestCompactProofOfTime(
                                    header.reward_chain_block.challenge_chain_sp_vdf,
                                    header.header_hash,
                                    header.height,
                                    uint8(CompressibleVDFField.CC_SP_VDF),
                                )
                            )

                        if (
                            header.challenge_chain_ip_proof.witness_type > 0
                            or not header.challenge_chain_ip_proof.normalized_to_identity
                        ):
                            broadcast_list.append(
                                timelord_protocol.RequestCompactProofOfTime(
                                    header.reward_chain_block.challenge_chain_ip_vdf,
                                    header.header_hash,
                                    header.height,
                                    uint8(CompressibleVDFField.CC_IP_VDF),
                                )
                            )
                        # This is the first header with uncompact proofs. Store its height so next time we iterate
                        # only from here. Fix header block iteration window to at least 1000, so reorgs will be
                        # handled correctly.
                        if prev_broadcast_list_len == 0 and len(broadcast_list) > 0 and h <= max(0, max_height - 1000):
                            new_min_height = header.height

                    # Small sleep between batches.
                    batches_finished += 1
                    if batches_finished % 10 == 0:
                        await asyncio.sleep(1)

                # We have no uncompact blocks, but mentain the block iteration window to at least 1000 blocks.
                if new_min_height is None:
                    new_min_height = max(0, max_height - 1000)
                min_height = new_min_height
                if len(broadcast_list) > target_uncompact_proofs:
                    random.shuffle(broadcast_list)
                    broadcast_list = broadcast_list[:target_uncompact_proofs]
                if self.sync_store.get_sync_mode():
                    continue
                if self.server is not None:
                    for new_pot in broadcast_list:
                        msg = make_msg(ProtocolMessageTypes.request_compact_proof_of_time, new_pot)
                        await self.server.send_to_all([msg], NodeType.TIMELORD)
                await asyncio.sleep(uncompact_interval_scan)
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception in broadcast_uncompact_blocks: {e}")
            self.log.error(f"Exception Stack: {error_stack}")
