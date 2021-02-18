import asyncio
import dataclasses
import logging
import random
import time
import traceback
from pathlib import Path
from typing import Optional, Dict, Callable, List, Tuple, Any, Union, Set

import aiosqlite
from blspy import AugSchemeMPL

import src.server.ws_connection as ws  # lgtm [py/import-and-import-from]
from src.consensus.block_creation import unfinished_block_to_full_block
from src.consensus.blockchain import Blockchain, ReceiveBlockResult
from src.consensus.constants import ConsensusConstants
from src.consensus.difficulty_adjustment import (
    get_sub_slot_iters_and_difficulty,
    can_finish_sub_and_full_epoch,
)
from src.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from src.consensus.multiprocess_validation import PreValidationResult
from src.consensus.pot_iterations import is_overflow_block, calculate_sp_iters
from src.consensus.block_record import BlockRecord
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore
from src.full_node.full_node_store import FullNodeStore
from src.full_node.mempool_manager import MempoolManager
from src.full_node.signage_point import SignagePoint
from src.full_node.sync_store import SyncStore
from src.full_node.weight_proof import WeightProofHandler
from src.protocols import (
    full_node_protocol,
    timelord_protocol,
    wallet_protocol,
    farmer_protocol,
)
from src.protocols.full_node_protocol import RequestBlocks, RejectBlocks, RespondBlocks, RespondBlock
from src.protocols.protocol_message_types import ProtocolMessageTypes

from src.server.node_discovery import FullNodePeers
from src.server.outbound_message import Message, NodeType, make_msg
from src.server.server import ChiaServer
from src.types.full_block import FullBlock
from src.types.blockchain_format.pool_target import PoolTarget
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock

from src.util.errors import ConsensusError, Err
from src.util.ints import uint32, uint128, uint8, uint64
from src.util.path import mkdir, path_from_root


class FullNode:
    block_store: BlockStore
    full_node_store: FullNodeStore
    full_node_peers: Optional[FullNodePeers]
    sync_store: SyncStore
    coin_store: CoinStore
    mempool_manager: MempoolManager
    connection: aiosqlite.Connection
    _sync_task: Optional[asyncio.Task]
    blockchain: Blockchain
    config: Dict
    server: Any
    log: logging.Logger
    constants: ConsensusConstants
    _shut_down: bool
    root_path: Path
    state_changed_callback: Optional[Callable]
    timelord_lock: asyncio.Lock

    def __init__(
        self,
        config: Dict,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
    ):
        self.root_path = root_path
        self.config = config
        self.server = None
        self._shut_down = False  # Set to true to close all infinite loops
        self.constants = consensus_constants
        self.pow_creation: Dict[uint32, asyncio.Event] = {}
        self.state_changed_callback: Optional[Callable] = None
        self.full_node_peers = None

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        db_path_replaced: str = config["database_path"].replace(
            "CHALLENGE", consensus_constants.GENESIS_CHALLENGE[:8].hex()
        )
        self.db_path = path_from_root(root_path, db_path_replaced)
        mkdir(self.db_path.parent)

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    async def _start(self):
        # create the store (db) and full node instance
        self.connection = await aiosqlite.connect(self.db_path)
        self.block_store = await BlockStore.create(self.connection)
        self.full_node_store = await FullNodeStore.create(self.constants)
        self.sync_store = await SyncStore.create()
        self.coin_store = await CoinStore.create(self.connection)
        self.timelord_lock = asyncio.Lock()
        self.log.info("Initializing blockchain from disk")
        start_time = time.time()
        self.blockchain = await Blockchain.create(self.coin_store, self.block_store, self.constants)
        self.mempool_manager = MempoolManager(self.coin_store, self.constants)
        self.weight_proof_handler = WeightProofHandler(self.constants, self.blockchain)
        self._sync_task = None
        time_taken = time.time() - start_time
        if self.blockchain.get_peak() is None:
            self.log.info(f"Initialized with empty blockchain time taken: {int(time_taken)}s")
        else:
            self.log.info(
                f"Blockchain initialized to peak {self.blockchain.get_peak().header_hash} height"
                f" {self.blockchain.get_peak().height}, "
                f"time taken: {int(time_taken)}s"
            )
            await self.mempool_manager.new_peak(self.blockchain.get_peak())

        self.state_changed_callback = None

        peak: Optional[BlockRecord] = self.blockchain.get_peak()
        if peak is not None:
            full_peak = await self.blockchain.get_full_peak()
            await self.peak_post_processing(full_peak, peak, peak.height - 1, None)

    def set_server(self, server: ChiaServer):
        self.server = server
        try:
            self.full_node_peers = FullNodePeers(
                self.server,
                self.root_path,
                self.config["target_peer_count"] - self.config["target_outbound_peer_count"],
                self.config["target_outbound_peer_count"],
                self.config["peer_db_path"],
                self.config["introducer_peer"],
                self.config["peer_connect_interval"],
                self.log,
            )
            asyncio.create_task(self.full_node_peers.start())
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            self.log.error(f"Exception in peer discovery: {e}")
            self.log.error(f"Exception Stack: {error_stack}")

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    async def short_sync_batch(self, peer: ws.WSChiaConnection, start_height: uint32, target_height: uint32) -> bool:
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
        self, peer: ws.WSChiaConnection, peak_height: uint32, target_height: uint32, target_unf_hash: bytes32
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
                fetch_tx: bool = unfinished_block is None and curr_height == target_height
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
                    await self.respond_block(response)
        except Exception as e:
            self.sync_store.backtrack_syncing[peer.peer_node_id] -= 1
            raise e

        self.sync_store.backtrack_syncing[peer.peer_node_id] -= 1
        return found_fork_point

    async def new_peak(self, request: full_node_protocol.NewPeak, peer: ws.WSChiaConnection):
        """
        We have received a notification of a new peak from a peer. This happens either when we have just connected,
        or when the peer has updated their peak.

        Args:
            request: information about the new peak
            peer: peer that sent the message

        """

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
                    return

            if request.height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
                # This is the case of syncing up more than a few blocks, at the start of the chain
                # TODO(almog): fix weight proofs so they work at the beginning as well
                self.log.debug("Doing batch sync, no backup")
                await self.short_sync_batch(peer, uint32(0), request.height)
                return

            if request.height < curr_peak_height + self.config["sync_blocks_behind_threshold"]:
                # This case of being behind but not by so much
                if await self.short_sync_batch(peer, uint32(max(curr_peak_height - 6, 0)), request.height):
                    return

            # This is the either the case where we were not able to sync successfully (for example, due to the fork
            # point being in the past), or we are very far behind. Performs a long sync.
            self._sync_task = asyncio.create_task(self._sync())

    async def send_peak_to_timelords(self, peak_block: Optional[FullBlock] = None):
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
            timelord_new_peak: timelord_protocol.NewPeakTimelord = timelord_protocol.NewPeakTimelord(
                peak_block.reward_chain_block,
                difficulty,
                peak.deficit,
                peak.sub_slot_iters,
                ses,
                recent_rc,
                last_csb_or_eos,
            )

            msg = make_msg(ProtocolMessageTypes.new_peak_timelord, timelord_new_peak)
            await self.server.send_to_all([msg], NodeType.TIMELORD)

    async def synced(self) -> bool:
        curr: Optional[BlockRecord] = self.blockchain.get_peak()
        if curr is None:
            return False

        while curr is not None and not curr.is_transaction_block:
            curr = self.blockchain.try_block_record(curr.prev_hash)

        now = time.time()
        if (
            curr is None
            or curr.timestamp is None
            or curr.timestamp < uint64(int(now - 60 * 20))
            or self.sync_store.get_sync_mode()
        ):
            return False
        else:
            return True

    async def on_connect(self, connection: ws.WSChiaConnection):
        """
        Whenever we connect to another node / wallet, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """

        self._state_changed("add_connection")
        if self.full_node_peers is not None:
            asyncio.create_task(self.full_node_peers.on_connect(connection))

        if connection.connection_type is NodeType.FULL_NODE:
            # Send filter to node and request mempool items that are not in it (Only if we are currently synced)
            synced = await self.synced()
            peak_height = self.blockchain.get_peak_height()
            if synced and peak_height is not None and peak_height > self.constants.INITIAL_FREEZE_PERIOD:
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

    def on_disconnect(self, connection: ws.WSChiaConnection):
        self.log.info(f"peer disconnected {connection.get_peer_info()}")
        self.sync_store.peer_disconnected(connection.peer_node_id)
        self._state_changed("close_connection")

    def _num_needed_peers(self) -> int:
        assert self.server is not None
        assert self.server.all_connections is not None
        diff = self.config["target_peer_count"] - len(self.server.all_connections)
        return diff if diff >= 0 else 0

    def _close(self):
        self._shut_down = True
        self.blockchain.shut_down()
        self.mempool_manager.shut_down()
        if self.full_node_peers is not None:
            asyncio.create_task(self.full_node_peers.close())

    async def _await_closed(self):
        try:
            if self._sync_task is not None:
                self._sync_task.cancel()
        except asyncio.TimeoutError:
            pass
        await self.connection.close()

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

        # Ensure we are only syncing once and not double calling this method
        if self.sync_store.get_sync_mode():
            return

        self.sync_store.set_sync_mode(True)
        self._state_changed("sync_mode")

        try:
            self.log.info("Starting to perform sync.")
            self.log.info("Waiting to receive peaks from peers.")

            # Wait until we have 3 peaks or up to a max of 30 seconds
            peaks = []
            for i in range(300):
                peaks = [tup[0] for tup in self.sync_store.get_peak_of_each_peer().values()]
                if len(self.sync_store.get_peers_that_have_peak(peaks)) < 3:
                    if self._shut_down:
                        return
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

            request = full_node_protocol.RequestProofOfWeight(heaviest_peak_height, heaviest_peak_hash)
            response = await weight_proof_peer.request_proof_of_weight(request, timeout=90)

            # Disconnect from this peer, because they have not behaved properly
            if response is None or not isinstance(response, full_node_protocol.RespondProofOfWeight):
                await weight_proof_peer.close()
                raise RuntimeError(f"Weight proof did not arrive in time from peer: {weight_proof_peer.peer_host}")
            if response.wp.recent_chain_data[-1].reward_chain_block.height != heaviest_peak_height:
                await weight_proof_peer.close()
                raise RuntimeError(f"Weight proof had the wrong height: {weight_proof_peer.peer_host}")
            if response.wp.recent_chain_data[-1].reward_chain_block.weight != heaviest_peak_weight:
                await weight_proof_peer.close()
                raise RuntimeError(f"Weight proof had the wrong weight: {weight_proof_peer.peer_host}")

            validated, fork_point = self.weight_proof_handler.validate_weight_proof(response.wp)
            if not validated:
                raise ValueError("Weight proof validation failed")

            self.log.info(f"Re-checked peers: total of {len(peers_with_peak)} peers with peak {heaviest_peak_height}")

            # Ensures that the fork point does not change
            async with self.blockchain.lock:
                await self.blockchain.warmup(fork_point)
                await self.sync_from_fork_point(fork_point, heaviest_peak_height, heaviest_peak_hash)
        except asyncio.CancelledError:
            self.log.warning("Syncing failed, CancelledError")
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Error with syncing: {type(e)}{tb}")
        finally:
            if self._shut_down:
                return
            await self._finish_sync()

    async def sync_from_fork_point(self, fork_point_height: int, target_peak_sb_height: uint32, peak_hash: bytes32):
        self.log.info(f"Start syncing from fork point at {fork_point_height} up to {target_peak_sb_height}")
        peer_ids: Set[bytes32] = self.sync_store.get_peers_that_have_peak([peak_hash])
        peers_with_peak: List = [c for c in self.server.all_connections.values() if c.peer_node_id in peer_ids]

        if len(peers_with_peak) == 0:
            raise RuntimeError(f"Not syncing, no peers with header_hash {peak_hash} ")
        advanced_peak = False
        batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
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
                response = await peer.request_blocks(request)
                if response is None:
                    await peer.close()
                    to_remove.append(peer)
                    continue
                if isinstance(response, RejectBlocks):
                    to_remove.append(peer)
                    continue
                elif isinstance(response, RespondBlocks):
                    success, advanced_peak, _ = await self.receive_block_batch(
                        response.blocks, peer, None if advanced_peak else uint32(fork_point_height)
                    )
                    if success is False:
                        await peer.close()
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
        self, blocks: List[FullBlock], peer: ws.WSChiaConnection, fork_point: Optional[uint32]
    ) -> Tuple[bool, bool, Optional[uint32]]:
        advanced_peak = False
        fork_height: Optional[uint32] = uint32(0)
        pre_validate_start = time.time()
        pre_validation_results: Optional[
            List[PreValidationResult]
        ] = await self.blockchain.pre_validate_blocks_multiprocessing(blocks)
        self.log.debug(f"Block pre-validation time: {time.time() - pre_validate_start}")
        if pre_validation_results is None:
            return False, False, None
        for i, block in enumerate(blocks):
            if pre_validation_results[i].error is not None:
                self.log.error(
                    f"Invalid block from peer: {peer.get_peer_info()} {Err(pre_validation_results[i].error)}"
                )
                return False, advanced_peak, fork_height

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
                await self.weight_proof_handler.create_prev_sub_epoch_segments()
        self._state_changed("new_peak")
        self.log.debug(
            f"Total time for {len(blocks)} blocks: {time.time() - pre_validate_start}, advanced: {advanced_peak}"
        )
        return True, advanced_peak, fork_height

    async def _finish_sync(self):
        """
        Finalize sync by setting sync mode to False, clearing all sync information, and adding any final
        blocks that we have finalized recently.
        """
        self.sync_store.set_sync_mode(False)
        self._state_changed("sync_mode")
        if self.server is None:
            return

        peak: Optional[BlockRecord] = self.blockchain.get_peak()
        async with self.blockchain.lock:
            await self.sync_store.clear_sync_info()

            peak_fb: FullBlock = await self.blockchain.get_full_peak()
            if peak is not None:
                await self.peak_post_processing(peak_fb, peak, peak.height - 1, None)

        if peak is not None:
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

    async def peak_post_processing(
        self, block: FullBlock, record: BlockRecord, fork_height: uint32, peer: Optional[ws.WSChiaConnection]
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
            f"sub slot iters: {sub_slot_iters}"
        )

        sub_slots = await self.blockchain.get_sp_and_ip_sub_slots(record.header_hash)
        assert sub_slots is not None

        if not self.sync_store.get_sync_mode():
            self.blockchain.clean_block_records()

        added_eos, _, _ = self.full_node_store.new_peak(
            record,
            sub_slots[0],
            sub_slots[1],
            fork_height != block.height - 1 and block.height != 0,
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

        # Update the mempool
        await self.mempool_manager.new_peak(self.blockchain.get_peak())

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

        # TODO: maybe broadcast new SP/IPs as well?
        if record.height % 1000 == 0:
            # Occasionally clear the seen list to keep it small
            self.full_node_store.clear_seen_unfinished_blocks()
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

        self._state_changed("new_peak")

    async def respond_block(
        self,
        respond_block: full_node_protocol.RespondBlock,
        peer: Optional[ws.WSChiaConnection] = None,
    ) -> Optional[Message]:
        """
        Receive a full block from a peer full node (or ourselves).
        """
        block: FullBlock = respond_block.block
        if self.sync_store.get_sync_mode():
            return None

        # Adds the block to seen, and check if it's seen before (which means header is in memory)
        header_hash = block.header_hash
        if self.blockchain.contains_block(header_hash):
            return None

        if block.is_transaction_block() and block.transactions_generator is None:
            # This is the case where we already had the unfinished block, and asked for this block without
            # the transactions (since we already had them). Therefore, here we add the transactions.
            unfinished_rh: bytes32 = block.reward_chain_block.get_unfinished().get_hash()
            unf_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(unfinished_rh)
            if unf_block is not None and unf_block.transactions_generator is not None:
                block = dataclasses.replace(block, transactions_generator=unf_block.transactions_generator)

        async with self.blockchain.lock:
            # After acquiring the lock, check again, because another asyncio thread might have added it
            if self.blockchain.contains_block(header_hash):
                return None
            validation_start = time.time()
            # Tries to add the block to the blockchain
            pre_validation_results: Optional[
                List[PreValidationResult]
            ] = await self.blockchain.pre_validate_blocks_multiprocessing([block])
            if pre_validation_results is None:
                raise ValueError(f"Failed to validate block {header_hash} height {block.height}")
            if pre_validation_results[0].error is not None:
                if Err(pre_validation_results[0].error) == Err.INVALID_PREV_BLOCK_HASH:
                    added: ReceiveBlockResult = ReceiveBlockResult.DISCONNECTED_BLOCK
                    error_code: Optional[Err] = Err.INVALID_PREV_BLOCK_HASH
                    fork_height: Optional[uint32] = None
                else:
                    raise ValueError(
                        f"Failed to validate block {header_hash} height "
                        f"{block.height}: {Err(pre_validation_results[0].error).name}"
                    )
            else:
                added, error_code, fork_height = await self.blockchain.receive_block(
                    block, pre_validation_results[0], None
                )

            validation_time = time.time() - validation_start

            if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
                return None
            elif added == ReceiveBlockResult.INVALID_BLOCK:
                assert error_code is not None
                self.log.error(f"Block {header_hash} at height {block.height} is invalid with code {error_code}.")
                raise ConsensusError(error_code, header_hash)

            elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
                self.log.info(f"Disconnected block {header_hash} at height {block.height}")
                return None
            elif added == ReceiveBlockResult.NEW_PEAK:
                # Only propagate blocks which extend the blockchain (becomes one of the heads)
                new_peak: Optional[BlockRecord] = self.blockchain.get_peak()
                assert new_peak is not None and fork_height is not None
                self.log.debug(f"Validation time for peak: {validation_time}")

                await self.peak_post_processing(block, new_peak, fork_height, peer)

            elif added == ReceiveBlockResult.ADDED_AS_ORPHAN:
                self.log.info(
                    f"Received orphan block of height {block.height} rh " f"{block.reward_chain_block.get_hash()}"
                )
            else:
                # Should never reach here, all the cases are covered
                raise RuntimeError(f"Invalid result from receive_block {added}")

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
        return None

    async def respond_unfinished_block(
        self,
        respond_unfinished_block: full_node_protocol.RespondUnfinishedBlock,
        peer: Optional[ws.WSChiaConnection],
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
            return

        # Adds the unfinished block to seen, and check if it's seen before, to prevent
        # processing it twice. This searches for the exact version of the unfinished block (there can be many different
        # foliages for the same trunk). This is intentional, to prevent DOS attacks.
        # Note that it does not require that this block was successfully processed
        if self.full_node_store.seen_unfinished_block(block.get_hash()):
            return

        block_hash = block.reward_chain_block.get_hash()

        # This searched for the trunk hash (unfinished reward hash). If we have already added a block with the same
        # hash, return
        if self.full_node_store.get_unfinished_block(block_hash) is not None:
            return

        peak: Optional[BlockRecord] = self.blockchain.get_peak()
        if peak is not None:
            if block.total_iters < peak.sp_total_iters(self.constants):
                # This means this unfinished block is pretty far behind, it will not add weight to our chain
                return

        if block.prev_header_hash == self.constants.GENESIS_CHALLENGE:
            prev_b = None
        else:
            prev_b = self.blockchain.block_record(block.prev_header_hash)

        is_overflow = is_overflow_block(self.constants, block.reward_chain_block.signage_point_index)

        # Count the blocks in sub slot, and check if it's a new epoch
        first_ss_new_epoch = False
        if len(block.finished_sub_slots) > 0:
            num_blocks_in_ss = 1  # Curr
            if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
                first_ss_new_epoch = True
        else:
            curr = self.blockchain.try_block_record(block.prev_header_hash)
            num_blocks_in_ss = 2  # Curr and prev
            while (curr is not None) and not curr.first_in_sub_slot:
                curr = self.blockchain.try_block_record(curr.prev_hash)
                num_blocks_in_ss += 1
            if (
                curr is not None
                and curr.first_in_sub_slot
                and curr.sub_epoch_summary_included is not None
                and curr.sub_epoch_summary_included.new_difficulty is not None
            ):
                first_ss_new_epoch = True
            elif prev_b is not None:
                # If the prev can finish an epoch, then we are in a new epoch
                prev_prev = self.blockchain.try_block_record(prev_b.prev_hash)
                _, can_finish_epoch = can_finish_sub_and_full_epoch(
                    self.constants,
                    prev_b.height,
                    prev_b.deficit,
                    self.blockchain,
                    prev_b.header_hash if prev_prev is not None else None,
                    False,
                )
                if can_finish_epoch:
                    first_ss_new_epoch = True

        if is_overflow and first_ss_new_epoch:
            # No overflow blocks in new epoch
            return
        if num_blocks_in_ss > self.constants.MAX_SUB_SLOT_BLOCKS:
            # TODO: count overflow blocks separately (also in validation)
            self.log.warning("Too many blocks added, not adding block")
            return

        async with self.blockchain.lock:
            # TODO: pre-validate VDFs outside of lock
            (
                required_iters,
                error_code,
            ) = await self.blockchain.validate_unfinished_block(block)
            if error_code is not None:
                raise ConsensusError(error_code)

        assert required_iters is not None

        # Perform another check, in case we have already concurrently added the same unfinished block
        if self.full_node_store.get_unfinished_block(block_hash) is not None:
            return

        if block.prev_header_hash == self.constants.GENESIS_CHALLENGE:
            height = uint32(0)
        else:
            height = uint32(self.blockchain.block_record(block.prev_header_hash).height + 1)

        ses: Optional[SubEpochSummary] = next_sub_epoch_summary(
            self.constants,
            self.blockchain,
            required_iters,
            block,
            True,
        )

        self.full_node_store.add_unfinished_block(height, block)
        if farmed_block is True:
            self.log.info(f"🍀 ️Farmed unfinished_block {block_hash}")
        else:
            self.log.info(f"Added unfinished_block {block_hash}, not farmed")

        sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
            self.constants,
            block,
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
                    return
            else:
                rc_prev = res[0].reward_chain.get_hash()
        else:
            assert block.reward_chain_block.reward_chain_sp_vdf is not None
            rc_prev = block.reward_chain_block.reward_chain_sp_vdf.challenge

        timelord_request = timelord_protocol.NewUnfinishedBlock(
            block.reward_chain_block,
            difficulty,
            sub_slot_iters,
            block.foliage,
            ses,
            rc_prev,
        )

        msg = make_msg(ProtocolMessageTypes.new_unfinished_block, timelord_request)
        await self.server.send_to_all([msg], NodeType.TIMELORD)

        full_node_request = full_node_protocol.NewUnfinishedBlock(block.reward_chain_block.get_hash())
        msg = make_msg(ProtocolMessageTypes.new_unfinished_block, full_node_request)
        if peer is not None:
            await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)
        else:
            await self.server.send_to_all([msg], NodeType.FULL_NODE)
        self._state_changed("unfinished_block")

    async def new_infusion_point_vdf(self, request: timelord_protocol.NewInfusionPointVDF) -> Optional[Message]:
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

        # Backtracks through end of slot objects, should work for multiple empty sub slots
        for eos, _, _ in reversed(self.full_node_store.finished_sub_slots):
            if eos is not None and eos.reward_chain.get_hash() == target_rc_hash:
                target_rc_hash = eos.reward_chain.end_of_slot_vdf.challenge
        if target_rc_hash == self.constants.GENESIS_CHALLENGE:
            prev_b = None
        else:
            # Find the prev block, starts looking backwards from the peak
            # TODO: should we look at end of slots too?
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

        # TODO: finished slots is not correct
        overflow = is_overflow_block(
            self.constants,
            unfinished_block.reward_chain_block.signage_point_index,
        )
        finished_sub_slots = self.full_node_store.get_finished_sub_slots(
            prev_b,
            self.blockchain,
            unfinished_block.reward_chain_block.pos_ss_cc_challenge_hash,
            overflow,
        )
        sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
            self.constants,
            dataclasses.replace(unfinished_block, finished_sub_slots=finished_sub_slots),
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
        first_ss_new_epoch = False
        if not self.has_valid_pool_sig(block):
            self.log.warning("Trying to make a pre-farm block but height is not 0")
            return None
        if len(block.finished_sub_slots) > 0:
            if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
                first_ss_new_epoch = True
        else:
            curr = prev_b
            while (curr is not None) and not curr.first_in_sub_slot:
                curr = self.blockchain.block_record(curr.prev_hash)
            if (
                curr is not None
                and curr.first_in_sub_slot
                and curr.sub_epoch_summary_included is not None
                and curr.sub_epoch_summary_included.new_difficulty is not None
            ):
                first_ss_new_epoch = True
        if first_ss_new_epoch and overflow:
            # No overflow blocks in the first sub-slot of each epoch
            return None
        try:
            await self.respond_block(full_node_protocol.RespondBlock(block))
        except ConsensusError as e:
            self.log.warning(f"Consensus error validating block: {e}")
        return None

    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: ws.WSChiaConnection
    ) -> Tuple[Optional[Message], bool]:

        fetched_ss = self.full_node_store.get_sub_slot(request.end_of_slot_bundle.challenge_chain.get_hash())
        if fetched_ss is not None:
            # Already have the sub-slot
            logging.getLogger(__name__).warning("1")
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
                logging.getLogger(__name__).warning("2")
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
                self.blockchain.get_peak(),
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
        logging.getLogger(__name__).warning("4")
        return None, False
