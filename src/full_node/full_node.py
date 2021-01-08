import asyncio
import dataclasses
import logging
import time
import traceback
from pathlib import Path
from typing import AsyncGenerator, Optional, Dict, Callable, List, Tuple, Any, Union, Set

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
from src.consensus.pot_iterations import is_overflow_sub_block, calculate_sp_iters
from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.block_cache import BlockCache
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
from src.protocols.full_node_protocol import RequestSubBlocks, RejectSubBlocks, RespondSubBlocks, RespondSubBlock

from src.server.node_discovery import FullNodePeers
from src.server.outbound_message import Message, NodeType, OutboundMessage
from src.server.server import ChiaServer
from src.types.full_block import FullBlock
from src.types.pool_target import PoolTarget
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock

from src.util.errors import ConsensusError
from src.util.ints import uint32, uint128, uint8
from src.util.path import mkdir, path_from_root

OutboundMessageGenerator = AsyncGenerator[OutboundMessage, None]


class FullNode:
    block_store: BlockStore
    full_node_store: FullNodeStore
    # full_node_peers: FullNodePeers
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
        self.pow_pending: Set[bytes32] = set()
        self.pow_creation: Dict[uint32, asyncio.Event] = {}
        self.state_changed_callback: Optional[Callable] = None

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.db_path = path_from_root(root_path, config["database_path"])
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
        self.weight_proof_handler = WeightProofHandler(
            self.constants,
            BlockCache(
                self.blockchain.sub_blocks,
                self.blockchain.sub_height_to_hash,
                {},
                self.blockchain.sub_epoch_summaries,
                self.block_store,
            ),
        )
        self._sync_task = None
        time_taken = time.time() - start_time
        if self.blockchain.get_peak() is None:
            self.log.info(f"Initialized with empty blockchain time taken: {int(time_taken)}s")
        else:
            self.log.info(
                f"Blockchain initialized to peak {self.blockchain.get_peak().header_hash} height"
                f" {self.blockchain.get_peak().sub_block_height}, "
                f"time taken: {int(time_taken)}s"
            )
            await self.mempool_manager.new_peak(self.blockchain.get_peak())

        self.state_changed_callback = None

        peak: Optional[SubBlockRecord] = self.blockchain.get_peak()
        if peak is not None:
            sp_sub_slot, ip_sub_slot = await self.blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
            self.full_node_store.new_peak(
                peak,
                sp_sub_slot,
                ip_sub_slot,
                False,
                self.blockchain.sub_blocks,
            )

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

    async def request_and_add_sub_block(self, peer: ws.WSChiaConnection, sub_height):
        peer_peak = await peer.request_sub_block(full_node_protocol.RequestSubBlock(uint32(sub_height), True))
        if peer_peak is None:
            self.log.warning(f"Failed to fetch sub block {sub_height} from {peer.get_peer_info()}")
            return
        if isinstance(peer_peak, full_node_protocol.RespondSubBlock):
            sub_block = peer_peak.sub_block
            self.sync_store.add_potential_peak(sub_block.header_hash, sub_block.sub_block_height, sub_block.weight)
            await self.respond_sub_block(peer_peak, peer)
        else:
            self.log.warning(f"Failed to fetch sub block {sub_height} from {peer.get_peer_info()}")

    async def new_peak(self, request, peer: ws.WSChiaConnection):
        # Check if we have this block in the blockchain
        if peer is not None and peer.peer_node_id is not None:
            self.sync_store.add_peak_peer(request.header_hash, peer.peer_node_id, request.sub_block_height)

        if self.blockchain.contains_sub_block(request.header_hash):
            return None
        # Not interested in less heavy peaks
        peak: Optional[SubBlockRecord] = self.blockchain.get_peak()
        if peak is not None and peak.weight > request.weight:
            return None

        if self.sync_store.get_sync_mode():
            # If peer connect while we are syncing, check if they have the block we are syncing towards
            peak_sync_hash = self.sync_store.get_sync_target_hash()
            peak_sync_height = self.sync_store.get_sync_target_height()
            if peak_sync_hash is not None and request.header_hash != peak_sync_hash and peak_sync_height is not None:
                peak_peers = self.sync_store.get_peak_peers(peak_sync_hash)
                # Don't ask if we already know this peer has the peak
                if peer.peer_node_id not in peak_peers:
                    target_peak_response: Optional[RespondSubBlock] = await peer.request_sub_block(
                        full_node_protocol.RequestSubBlock(uint32(peak_sync_height), True)
                    )
                    if target_peak_response is not None and isinstance(target_peak_response, RespondSubBlock):
                        self.sync_store.add_peak_peer(peak_sync_hash, peer.peer_node_id, peak_sync_height)
        elif request.sub_block_height < self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
            self.log.info("not enough blocks for weight proof,request peak sub block")
            await self.request_and_add_sub_block(peer, request.sub_block_height)
        elif (
            peak is not None
            and peak.sub_block_height > request.sub_block_height - self.constants.WEIGHT_PROOF_RECENT_BLOCKS
        ):
            await self.request_and_add_sub_block(peer, request.sub_block_height)
        else:
            await self.request_proof_of_weight(peer, request.sub_block_height, request.header_hash)

    async def request_proof_of_weight(self, peer, height, header_hash):
        if peer.peer_node_id in self.pow_pending:
            self.log.info(f"Already have pending proof-of-weight request for peer: {peer.get_peer_info()}")
            return
        self.pow_pending.add(peer.peer_node_id)
        request = full_node_protocol.RequestProofOfWeight(height, header_hash)
        response = await peer.request_proof_of_weight(request)
        self.pow_pending.remove(peer.peer_node_id)
        if response is not None and isinstance(response, full_node_protocol.RespondProofOfWeight):
            validated, fork_point = self.weight_proof_handler.validate_weight_proof(response.wp)
            if validated is True:
                # get tip params
                tip_weight = response.wp.recent_chain_data[-1].reward_chain_sub_block.weight
                tip_height = response.wp.recent_chain_data[-1].reward_chain_sub_block.sub_block_height
                self.sync_store.add_potential_peak(response.tip, tip_height, tip_weight)
                self.sync_store.add_potential_fork_point(response.tip, fork_point)
                msg = Message(
                    "request_sub_block",
                    full_node_protocol.RequestSubBlock(uint32(tip_height), True),
                )
                await peer.send_message(msg)
        return None

    async def send_peak_to_timelords(self):
        """
        Sends current peak to timelords
        """
        peak_block = await self.blockchain.get_full_peak()
        if peak_block is not None:
            peak = self.blockchain.sub_blocks[peak_block.header_hash]
            difficulty = self.blockchain.get_next_difficulty(peak.header_hash, False)
            ses: Optional[SubEpochSummary] = next_sub_epoch_summary(
                self.constants,
                self.blockchain.sub_blocks,
                self.blockchain.sub_height_to_hash,
                peak.required_iters,
                peak_block,
                True,
            )
            recent_rc = self.blockchain.get_recent_reward_challenges()

            curr = peak
            while not curr.is_challenge_sub_block(self.constants) and not curr.first_in_sub_slot:
                curr = self.blockchain.sub_blocks[curr.prev_hash]

            if curr.is_challenge_sub_block(self.constants):
                last_csb_or_eos = curr.total_iters
            else:
                last_csb_or_eos = curr.ip_sub_slot_total_iters(self.constants)
            timelord_new_peak: timelord_protocol.NewPeak = timelord_protocol.NewPeak(
                peak_block.reward_chain_sub_block,
                difficulty,
                peak.deficit,
                peak.sub_slot_iters,
                ses,
                recent_rc,
                last_csb_or_eos,
            )

            msg = Message("new_peak", timelord_new_peak)
            await self.server.send_to_all([msg], NodeType.TIMELORD)

    async def on_connect(self, connection: ws.WSChiaConnection):
        """
        Whenever we connect to another node / wallet, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """

        self._state_changed("add_connection")
        if self.full_node_peers is not None:
            asyncio.create_task(self.full_node_peers.on_connect(connection))

        if connection.connection_type is NodeType.FULL_NODE:
            # Send filter to node and request mempool items that are not in it
            my_filter = self.mempool_manager.get_filter()
            mempool_request = full_node_protocol.RequestMempoolTransactions(my_filter)

            msg = Message("request_mempool_transactions", mempool_request)
            await connection.send_message(msg)

        peak_full: Optional[FullBlock] = await self.blockchain.get_full_peak()

        if peak_full is not None:
            peak: SubBlockRecord = self.blockchain.sub_blocks[peak_full.header_hash]
            if connection.connection_type is NodeType.FULL_NODE:
                request_node = full_node_protocol.NewPeak(
                    peak.header_hash,
                    peak.sub_block_height,
                    peak.weight,
                    peak.sub_block_height,
                    peak_full.reward_chain_sub_block.get_unfinished().get_hash(),
                )
                await connection.send_message(Message("new_peak", request_node))

            elif connection.connection_type is NodeType.WALLET:
                # If connected to a wallet, send the Peak
                request_wallet = wallet_protocol.NewPeak(
                    peak.header_hash,
                    peak.sub_block_height,
                    peak.weight,
                    peak.sub_block_height,
                )
                await connection.send_message(Message("new_peak", request_wallet))
            elif connection.connection_type is NodeType.TIMELORD:
                await self.send_peak_to_timelords()

    def on_disconnect(self, connection: ws.WSChiaConnection):
        self.log.info(f"peer disconnected {connection.get_peer_info()}")
        self._state_changed("close_connection")

    def _num_needed_peers(self) -> int:
        assert self.server is not None
        assert self.server.all_connections is not None
        diff = self.config["target_peer_count"] - len(self.server.all_connections)
        return diff if diff >= 0 else 0

    def _close(self):
        self._shut_down = True
        self.blockchain.shut_down()
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
        Performs a full sync of the blockchain.
            - Check which are the heaviest peaks
            - Request headers for the heaviest
            - Find the fork point to see where to start downloading headers
            - Verify the weight of the tip, using the headers
            - Download all blocks
            - Disconnect peers that provide invalid blocks or don't have the blocks
        """
        try:
            self.log.info("Starting to perform sync with peers.")
            self.log.info("Waiting to receive peaks from peers.")
            self.sync_peers_handler = None
            self.sync_store.waiting_for_peaks = True

            await asyncio.sleep(2)
            # Based on responses from peers about the current heads, see which head is the heaviest
            # (similar to longest chain rule).
            self.sync_store.waiting_for_peaks = False
            potential_peaks: List[Tuple[bytes32, Tuple[uint32, uint128]]] = self.sync_store.get_potential_peaks_tuples()
            self.log.info(f"Have collected {len(potential_peaks)} potential peaks")
            if self._shut_down:
                return

            heaviest_peak_hash: Optional[bytes32] = None
            heaviest_peak_weight: Optional[uint128] = None
            heaviest_peak_height: Optional[uint32] = None
            for header_hash, height_weight_tuple in potential_peaks:
                height = height_weight_tuple[0]
                weight = height_weight_tuple[1]
                if heaviest_peak_hash is None or weight > heaviest_peak_height:
                    heaviest_peak_hash = header_hash
                    heaviest_peak_weight = weight
                    heaviest_peak_height = height

            if heaviest_peak_hash is None:
                self.log.info("Not performing sync, no peaks collected")
                return

            if self.blockchain.get_peak() is not None and heaviest_peak_weight <= self.blockchain.get_peak().weight:
                self.log.info("Not performing sync, already caught up.")
                return

            fork_point_height = self.sync_store.get_potential_fork_point(heaviest_peak_hash)

            await self.sync_from_fork_point(fork_point_height, heaviest_peak_height, heaviest_peak_hash)
        except asyncio.CancelledError:
            self.log.warning("Syncing failed, CancelledError")
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Error with syncing: {type(e)}{tb}")
        finally:
            if self._shut_down:
                return
            await self._finish_sync()

    def get_peers_with_peak(self, peak_hash) -> List[ws.WSChiaConnection]:
        filtered_peers: List[ws.WSChiaConnection] = []
        peers_with_peak = self.sync_store.get_peak_peers(peak_hash)
        for peer_hash in peers_with_peak:
            if peer_hash in self.server.all_connections:
                peer = self.server.all_connections[peer_hash]
                filtered_peers.append(peer)
        return filtered_peers

    async def sync_from_fork_point(self, fork_point_height: int, target_peak_sb_height: uint32, peak_hash):
        self.log.info(f"start syncing from fork point at {fork_point_height}")
        self.sync_store.set_peak_target(peak_hash, target_peak_sb_height)
        peers_with_peak = self.get_peers_with_peak(peak_hash)

        if len(peers_with_peak) == 0:
            self.log.warning(f"Not syncing, no peers with header_hash {peak_hash} ")
            return

        batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
        for i in range(fork_point_height, target_peak_sb_height, batch_size):
            start_height = i
            end_height = min(target_peak_sb_height, start_height + batch_size)
            request = RequestSubBlocks(uint32(start_height), uint32(end_height), True)
            self.log.info(f"Requesting sub blocks:  {start_height} to {end_height}")
            peers_to_remove = []
            batch_added = False
            to_remove = []
            for peer in peers_with_peak:
                if peer.closed:
                    to_remove.append(peer)
                    continue
                response = await peer.request_sub_blocks(request)
                if response is None:
                    peers_to_remove.append(peer)
                    continue
                if isinstance(response, RejectSubBlocks):
                    peers_to_remove.append(peer)
                    continue
                elif isinstance(response, RespondSubBlocks):
                    success = await self.receive_sub_block_batch(response.sub_blocks, peer)
                    if success is False:
                        await peer.close()
                        continue
                    else:
                        batch_added = True
                        break

            for peer in to_remove:
                peers_with_peak.remove(peer)

            if self.sync_store.peers_changed.is_set():
                peers_with_peak = self.get_peers_with_peak(peak_hash)
                self.sync_store.peers_changed.clear()

            if batch_added is False:
                self.log.info(f"Failed to fetch blocks {start_height} to {end_height} from peers: {peers_with_peak}")
                break

    async def receive_sub_block_batch(self, blocks: List[FullBlock], peer: ws.WSChiaConnection) -> bool:
        async with self.blockchain.lock:
            pre_validation_results = await self.blockchain.pre_validate_blocks_multiprocessing(blocks)
            for i, block in enumerate(blocks):
                if pre_validation_results is None:
                    return False
                req_iters = pre_validation_results[i]
                assert req_iters is not None
                (
                    result,
                    error,
                    fork_height,
                ) = await self.blockchain.receive_block(block, True, req_iters)
                if result == ReceiveBlockResult.INVALID_BLOCK or result == ReceiveBlockResult.DISCONNECTED_BLOCK:
                    if error is not None:
                        self.log.info(f"Error: {error}, Invalid block from peer: {peer.get_peer_info()} ")
                    return False
        self._state_changed("new_peak")
        return True

    async def _finish_sync(self):
        """
        Finalize sync by setting sync mode to False, clearing all sync information, and adding any final
        blocks that we have finalized recently.
        """
        if self.server is None:
            return

        potential_fut_blocks = (self.sync_store.get_potential_future_blocks()).copy()
        self.sync_store.set_sync_mode(False)

        async with self.blockchain.lock:
            await self.sync_store.clear_sync_info()

        for block in potential_fut_blocks:
            if self._shut_down:
                return
            await self.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        # Update timelords with most recent information
        await self.send_peak_to_timelords()

        peak: SubBlockRecord = self.blockchain.get_peak()
        peak_fb: FullBlock = await self.blockchain.get_full_peak()
        if peak is not None:
            # Adjust full node store
            sub_slots = await self.blockchain.get_sp_and_ip_sub_slots(peak_fb.header_hash)
            assert sub_slots is not None

            self.full_node_store.new_peak(
                peak,
                sub_slots[0],
                sub_slots[1],
                True,
                self.blockchain.sub_blocks,
            )
            await self.weight_proof_handler.get_proof_of_weight(peak.header_hash)
            request_wallet = wallet_protocol.NewPeak(
                peak.header_hash,
                peak.sub_block_height,
                peak.weight,
                peak.sub_block_height,
            )
            msg = Message("new_peak", request_wallet)
            await self.server.send_to_all([msg], NodeType.WALLET)
            self._state_changed("sub_block")

    def has_valid_pool_sig(self, block: Union[UnfinishedBlock, FullBlock]):
        if (
            block.foliage_sub_block.foliage_sub_block_data.pool_target
            == PoolTarget(self.constants.GENESIS_PRE_FARM_POOL_PUZZLE_HASH, uint32(0))
            and block.foliage_sub_block.prev_sub_block_hash != self.constants.GENESIS_PREV_HASH
        ):
            if not AugSchemeMPL.verify(
                block.reward_chain_sub_block.proof_of_space.pool_public_key,
                bytes(block.foliage_sub_block.foliage_sub_block_data.pool_target),
                block.foliage_sub_block.foliage_sub_block_data.pool_signature,
            ):
                return False
        return True

    async def respond_sub_block(
        self,
        respond_sub_block: full_node_protocol.RespondSubBlock,
        peer: Optional[ws.WSChiaConnection] = None,
    ) -> Optional[Message]:
        """
        Receive a full block from a peer full node (or ourselves).
        """
        sub_block: FullBlock = respond_sub_block.sub_block
        if self.sync_store.get_sync_mode():
            # This is a peak sent to us by another peer
            self.sync_store.add_potential_peak(sub_block.header_hash, sub_block.sub_block_height, sub_block.weight)
            return None

        # Adds the block to seen, and check if it's seen before (which means header is in memory)
        header_hash = sub_block.foliage_sub_block.get_hash()
        if self.blockchain.contains_sub_block(header_hash):
            return None

        if sub_block.transactions_generator is None:
            # This is the case where we already had the unfinished block, and asked for this sub-block without
            # the transactions (since we already had them). Therefore, here we add the transactions.
            unfinished_rh: bytes32 = sub_block.reward_chain_sub_block.get_unfinished().get_hash()
            unf_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(unfinished_rh)
            if unf_block is not None and unf_block.transactions_generator is not None:
                sub_block = dataclasses.replace(sub_block, transactions_generator=unf_block.transactions_generator)

        async with self.blockchain.lock:
            # Tries to add the block to the blockchain
            added, error_code, fork_height = await self.blockchain.receive_block(sub_block, False)
            if added == ReceiveBlockResult.NEW_PEAK:
                await self.mempool_manager.new_peak(self.blockchain.get_peak())
                self._state_changed("new_peak")

        if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
            return None
        elif added == ReceiveBlockResult.INVALID_BLOCK:
            assert error_code is not None
            self.log.error(
                f"Block {header_hash} at height {sub_block.sub_block_height} is invalid with code {error_code}."
            )
            raise ConsensusError(error_code, header_hash)

        elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
            self.log.info(f"Disconnected block {header_hash} at height {sub_block.sub_block_height}")
            peak = self.blockchain.get_peak()
            if peak is None:
                peak_height = -1
            else:
                peak_height = peak.sub_block_height
            if sub_block.sub_block_height > peak_height + self.config["sync_blocks_behind_threshold"]:
                if peak_height > sub_block.sub_block_height - self.constants.WEIGHT_PROOF_RECENT_BLOCKS:
                    msg = Message(
                        "request_sub_block",
                        full_node_protocol.RequestSubBlock(uint32(sub_block.sub_block_height - 1), True),
                    )
                    self.full_node_store.add_disconnected_block(sub_block)
                    if peer is not None:
                        await peer.send_message(msg)
                    else:
                        return msg
                else:
                    async with self.blockchain.lock:
                        if self.sync_store.get_sync_mode():
                            return None
                        self.sync_store.set_sync_mode(True)
                    self.log.info(
                        f"We are too far behind this block. Our height is {peak_height} and block is at "
                        f"{sub_block.sub_block_height}"
                    )
                    # Performs sync, and catch exceptions so we don't close the connection
                    self._sync_task = asyncio.create_task(self._sync())

            elif sub_block.sub_block_height >= peak_height - 5:
                # Allows shallow reorgs by simply requesting the previous height repeatedly
                # TODO: replace with fetching multiple blocks at once
                self.log.info(
                    f"We have received a disconnected block at height {sub_block.sub_block_height}, "
                    f"current peak is {peak_height}"
                )
                msg = Message(
                    "request_sub_block",
                    full_node_protocol.RequestSubBlock(uint32(sub_block.sub_block_height - 1), True),
                )
                self.full_node_store.add_disconnected_block(sub_block)
                if peer is not None:
                    await peer.send_message(msg)
                else:
                    return msg
            return None
        elif added == ReceiveBlockResult.NEW_PEAK:
            # Only propagate blocks which extend the blockchain (becomes one of the heads)
            new_peak: Optional[SubBlockRecord] = self.blockchain.get_peak()
            assert new_peak is not None
            assert fork_height is not None
            self.log.info(
                f"🌱 Updated peak to height {new_peak.sub_block_height}, weight {new_peak.weight}, "
                f"hh {new_peak.header_hash}, "
                f"forked at {fork_height}, rh: {new_peak.reward_infusion_new_challenge}, "
                f"total iters: {new_peak.total_iters}, "
                f"overflow: {new_peak.overflow}, "
                f"deficit: {new_peak.deficit}"
            )

            difficulty = self.blockchain.get_next_difficulty(new_peak.header_hash, False)
            sub_slot_iters = self.blockchain.get_next_slot_iters(new_peak.header_hash, False)
            self.log.info(f"Difficulty {difficulty} slot iterations {sub_slot_iters}")

            sub_slots = await self.blockchain.get_sp_and_ip_sub_slots(sub_block.header_hash)
            assert sub_slots is not None

            added_eos, added_sps, new_ips = self.full_node_store.new_peak(
                new_peak,
                sub_slots[0],
                sub_slots[1],
                fork_height != sub_block.sub_block_height - 1 and sub_block.sub_block_height != 0,
                self.blockchain.sub_blocks,
            )
            if sub_slots[1] is None:
                assert new_peak.ip_sub_slot_total_iters(self.constants) == 0
            # Ensure the signage point is also in the store, for consistency
            self.full_node_store.new_signage_point(
                new_peak.signage_point_index,
                self.blockchain.sub_blocks,
                new_peak,
                new_peak.sub_slot_iters,
                SignagePoint(
                    sub_block.reward_chain_sub_block.challenge_chain_sp_vdf,
                    sub_block.challenge_chain_sp_proof,
                    sub_block.reward_chain_sub_block.reward_chain_sp_vdf,
                    sub_block.reward_chain_sp_proof,
                ),
            )
            # TODO: maybe broadcast new SP/IPs as well?

            # If there were pending end of slots that happen after this peak, broadcast them if they are added
            if added_eos is not None:
                broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                    added_eos.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                    added_eos.challenge_chain.get_hash(),
                    uint8(0),
                    added_eos.reward_chain.end_of_slot_vdf.challenge,
                )
                msg = Message("new_signage_point_or_end_of_sub_slot", broadcast)
                await self.server.send_to_all([msg], NodeType.FULL_NODE)

            if new_peak.sub_block_height % 1000 == 0:
                # Occasionally clear the seen list to keep it small
                self.full_node_store.clear_seen_unfinished_blocks()

            if self.sync_store.get_sync_mode() is False:
                await self.send_peak_to_timelords()

                # Tell full nodes about the new peak
                msg = Message(
                    "new_peak",
                    full_node_protocol.NewPeak(
                        sub_block.header_hash,
                        sub_block.sub_block_height,
                        sub_block.weight,
                        fork_height,
                        sub_block.reward_chain_sub_block.get_unfinished().get_hash(),
                    ),
                )
                if peer is not None:
                    await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)
                else:
                    await self.server.send_to_all([msg], NodeType.FULL_NODE)

            # Tell wallets about the new peak
            msg = Message(
                "new_peak",
                wallet_protocol.NewPeak(
                    sub_block.header_hash,
                    sub_block.sub_block_height,
                    sub_block.weight,
                    fork_height,
                ),
            )
            await self.server.send_to_all([msg], NodeType.WALLET)

        elif added == ReceiveBlockResult.ADDED_AS_ORPHAN:
            self.log.warning(
                f"Received orphan block of height {sub_block.sub_block_height} rh "
                f"{sub_block.reward_chain_sub_block.get_hash()}"
            )
        else:
            # Should never reach here, all the cases are covered
            raise RuntimeError(f"Invalid result from receive_block {added}")

        # This code path is reached if added == ADDED_AS_ORPHAN or NEW_TIP
        next_block: Optional[FullBlock] = self.full_node_store.get_disconnected_block_by_prev(sub_block.header_hash)

        # Recursively process the next block if we have it
        if next_block is not None:
            await self.respond_sub_block(full_node_protocol.RespondSubBlock(next_block))
        peak = self.blockchain.get_peak()
        assert peak is not None

        # Removes all temporary data for old blocks
        clear_height = uint32(max(0, peak.sub_block_height - 50))
        self.full_node_store.clear_candidate_blocks_below(clear_height)
        self.full_node_store.clear_disconnected_blocks_below(clear_height)
        self.full_node_store.clear_unfinished_blocks_below(clear_height)
        self._state_changed("sub_block")
        return None

    async def respond_unfinished_sub_block(
        self,
        respond_unfinished_sub_block: full_node_protocol.RespondUnfinishedSubBlock,
        peer: Optional[ws.WSChiaConnection],
        farmed_block: bool = False,
    ):
        """
        We have received an unfinished sub-block, either created by us, or from another peer.
        We can validate it and if it's a good block, propagate it to other peers and
        timelords.
        """
        block = respond_unfinished_sub_block.unfinished_sub_block

        # Adds the unfinished block to seen, and check if it's seen before, to prevent
        # processing it twice. This searches for the exact version of the unfinished block (there can be many different
        # foliages for the same trunk). This is intentional, to prevent DOS attacks.
        # Note that it does not require that this block was successfully processed
        if self.full_node_store.seen_unfinished_block(block.get_hash()):
            return

        # This searched for the trunk hash (unfinished reward hash). If we have already added a block with the same
        # hash, return
        if self.full_node_store.get_unfinished_block(block.reward_chain_sub_block.get_hash()) is not None:
            return

        if block.prev_header_hash != self.constants.GENESIS_PREV_HASH and not self.blockchain.contains_sub_block(
            block.prev_header_hash
        ):
            # No need to request the parent, since the peer will send it to us anyway, via NewPeak
            self.log.info("Received a disconnected unfinished block")
            return

        peak: Optional[SubBlockRecord] = self.blockchain.get_peak()
        if peak is not None:
            if block.total_iters < peak.sp_total_iters(self.constants):
                # This means this unfinished block is pretty far behind, it will not add weight to our chain
                return

        prev_sb = (
            None
            if block.prev_header_hash == self.constants.GENESIS_PREV_HASH
            else self.blockchain.sub_blocks[block.prev_header_hash]
        )

        is_overflow = is_overflow_sub_block(self.constants, block.reward_chain_sub_block.signage_point_index)

        # Count the sub-blocks in sub slot, and check if it's a new epoch
        first_ss_new_epoch = False
        if len(block.finished_sub_slots) > 0:
            num_sub_blocks_in_ss = 1  # Curr
            if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
                first_ss_new_epoch = True
        else:
            curr = self.blockchain.sub_blocks.get(block.prev_header_hash, None)
            num_sub_blocks_in_ss = 2  # Curr and prev
            while (curr is not None) and not curr.first_in_sub_slot:
                curr = self.blockchain.sub_blocks.get(curr.prev_hash, None)
                num_sub_blocks_in_ss += 1
            if (
                curr is not None
                and curr.first_in_sub_slot
                and curr.sub_epoch_summary_included is not None
                and curr.sub_epoch_summary_included.new_difficulty is not None
            ):
                first_ss_new_epoch = True
            elif prev_sb is not None:
                # If the prev can finish an epoch, then we are in a new epoch
                prev_prev = self.blockchain.sub_blocks.get(prev_sb.prev_hash, None)
                _, can_finish_epoch = can_finish_sub_and_full_epoch(
                    self.constants,
                    prev_sb.sub_block_height,
                    prev_sb.deficit,
                    self.blockchain.sub_blocks,
                    prev_sb.header_hash if prev_prev is not None else None,
                    False,
                )
                if can_finish_epoch:
                    first_ss_new_epoch = True

        if is_overflow and first_ss_new_epoch:
            # No overflow sub-blocks in new epoch
            return
        if num_sub_blocks_in_ss > self.constants.MAX_SUB_SLOT_SUB_BLOCKS:
            # TODO: count overflow blocks separately (also in validation)
            self.log.warning("Too many sub-blocks added, not adding sub-block")
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
        if self.full_node_store.get_unfinished_block(block.reward_chain_sub_block.get_hash()) is not None:
            return

        if block.prev_header_hash == self.constants.GENESIS_PREV_HASH:
            sub_height = uint32(0)
        else:
            sub_height = uint32(self.blockchain.sub_blocks[block.prev_header_hash].sub_block_height + 1)

        ses: Optional[SubEpochSummary] = next_sub_epoch_summary(
            self.constants,
            self.blockchain.sub_blocks,
            self.blockchain.sub_height_to_hash,
            required_iters,
            block,
            True,
        )

        self.full_node_store.add_unfinished_block(sub_height, block)
        if farmed_block is True:
            self.log.info(f"🍀 ️Farmed unfinished_block {block.partial_hash}")
        else:
            self.log.info(f"Added unfinished_block {block.partial_hash}, not farmed")

        sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
            self.constants,
            block,
            self.blockchain.sub_height_to_hash,
            prev_sb,
            self.blockchain.sub_blocks,
        )

        if block.reward_chain_sub_block.signage_point_index == 0:
            res = self.full_node_store.get_sub_slot(block.reward_chain_sub_block.pos_ss_cc_challenge_hash)
            if res is None:
                if block.reward_chain_sub_block.pos_ss_cc_challenge_hash == self.constants.FIRST_CC_CHALLENGE:
                    rc_prev = self.constants.FIRST_RC_CHALLENGE
                else:
                    self.log.warning(f"Do not have sub slot {block.reward_chain_sub_block.pos_ss_cc_challenge_hash}")
                    return
            else:
                rc_prev = res[0].reward_chain.get_hash()
        else:
            assert block.reward_chain_sub_block.reward_chain_sp_vdf is not None
            rc_prev = block.reward_chain_sub_block.reward_chain_sp_vdf.challenge

        timelord_request = timelord_protocol.NewUnfinishedSubBlock(
            block.reward_chain_sub_block,
            difficulty,
            sub_slot_iters,
            block.foliage_sub_block,
            ses,
            rc_prev,
        )

        msg = Message("new_unfinished_sub_block", timelord_request)
        await self.server.send_to_all([msg], NodeType.TIMELORD)

        full_node_request = full_node_protocol.NewUnfinishedSubBlock(block.reward_chain_sub_block.get_hash())
        msg = Message("new_unfinished_sub_block", full_node_request)
        if peer is not None:
            await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)
        else:
            await self.server.send_to_all([msg], NodeType.FULL_NODE)
        self._state_changed("unfinished_sub_block")

    async def new_infusion_point_vdf(self, request: timelord_protocol.NewInfusionPointVDF) -> Optional[Message]:
        # Lookup unfinished blocks
        async with self.timelord_lock:
            unfinished_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(
                request.unfinished_reward_hash
            )

            if unfinished_block is None:
                self.log.warning(
                    f"Do not have unfinished reward chain block {request.unfinished_reward_hash}, cannot finish."
                )
                return None

            prev_sb: Optional[SubBlockRecord] = None

            target_rc_hash = request.reward_chain_ip_vdf.challenge

            # Backtracks through end of slot objects, should work for multiple empty sub slots
            for eos, _, _ in reversed(self.full_node_store.finished_sub_slots):
                if eos is not None and eos.reward_chain.get_hash() == target_rc_hash:
                    target_rc_hash = eos.reward_chain.end_of_slot_vdf.challenge
            if target_rc_hash == self.constants.FIRST_RC_CHALLENGE:
                prev_sb = None
            else:
                # Find the prev block, starts looking backwards from the peak
                # TODO: should we look at end of slots too?
                curr: Optional[SubBlockRecord] = self.blockchain.get_peak()

                for _ in range(10):
                    if curr is None:
                        break
                    if curr.reward_infusion_new_challenge == target_rc_hash:
                        # Found our prev block
                        prev_sb = curr
                        break
                    curr = self.blockchain.sub_blocks.get(curr.prev_hash, None)

                # If not found, cache keyed on prev block
                if prev_sb is None:
                    self.full_node_store.add_to_future_ip(request)
                    self.log.warning(f"Previous block is None, infusion point {request.reward_chain_ip_vdf.challenge}")
                    return None

            # TODO: finished slots is not correct
            overflow = is_overflow_sub_block(
                self.constants,
                unfinished_block.reward_chain_sub_block.signage_point_index,
            )
            finished_sub_slots = self.full_node_store.get_finished_sub_slots(
                prev_sb,
                self.blockchain.sub_blocks,
                unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash,
                overflow,
            )
            sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
                self.constants,
                dataclasses.replace(unfinished_block, finished_sub_slots=finished_sub_slots),
                self.blockchain.sub_height_to_hash,
                prev_sb,
                self.blockchain.sub_blocks,
            )

            if unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash == self.constants.FIRST_CC_CHALLENGE:
                sub_slot_start_iters = uint128(0)
            else:
                ss_res = self.full_node_store.get_sub_slot(
                    unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash
                )
                if ss_res is None:
                    self.log.warning(
                        f"Do not have sub slot {unfinished_block.reward_chain_sub_block.pos_ss_cc_challenge_hash}"
                    )
                    return None
                _, _, sub_slot_start_iters = ss_res
            sp_total_iters = uint128(
                sub_slot_start_iters
                + calculate_sp_iters(
                    self.constants,
                    sub_slot_iters,
                    unfinished_block.reward_chain_sub_block.signage_point_index,
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
                prev_sb,
                self.blockchain.sub_blocks,
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
                curr = prev_sb
                while (curr is not None) and not curr.first_in_sub_slot:
                    curr = self.blockchain.sub_blocks.get(curr.prev_hash, None)
                if (
                    curr is not None
                    and curr.first_in_sub_slot
                    and curr.sub_epoch_summary_included is not None
                    and curr.sub_epoch_summary_included.new_difficulty is not None
                ):
                    first_ss_new_epoch = True
            if first_ss_new_epoch and overflow:
                # No overflow sub-blocks in the first sub-slot of each epoch
                return None
            try:
                await self.respond_sub_block(full_node_protocol.RespondSubBlock(block))
            except ConsensusError as e:
                self.log.warning(f"Consensus error validating sub-block: {e}")
        return None

    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: ws.WSChiaConnection
    ) -> Tuple[Optional[Message], bool]:

        async with self.timelord_lock:
            fetched_ss = self.full_node_store.get_sub_slot(
                request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            )
            if (
                (fetched_ss is None)
                and request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
                != self.constants.FIRST_CC_CHALLENGE
            ):
                # If we don't have the prev, request the prev instead
                full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
                    request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                    uint8(0),
                    bytes([0] * 32),
                )
                return (
                    Message("request_signage_point_or_end_of_sub_slot", full_node_request),
                    False,
                )

            peak = self.blockchain.get_peak()
            if peak is not None and peak.sub_block_height > 2:
                next_sub_slot_iters = self.blockchain.get_next_slot_iters(peak.header_hash, True)
                next_difficulty = self.blockchain.get_next_difficulty(peak.header_hash, True)
            else:
                next_sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING
                next_difficulty = self.constants.DIFFICULTY_STARTING

            # Adds the sub slot and potentially get new infusions
            new_infusions = self.full_node_store.new_finished_sub_slot(
                request.end_of_slot_bundle,
                self.blockchain.sub_blocks,
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
                msg = Message("new_signage_point_or_end_of_sub_slot", broadcast)
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
                msg = Message("new_signage_point", broadcast_farmer)
                await self.server.send_to_all([msg], NodeType.FARMER)
                return None, True
            else:
                self.log.warning(
                    f"End of slot not added CC challenge "
                    f"{request.end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge}"
                )
        return None, False
