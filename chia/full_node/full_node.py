from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import multiprocessing
from multiprocessing.context import BaseContext
import random
import time
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

import sqlite3
from blspy import AugSchemeMPL

import chia.server.ws_connection as ws  # lgtm [py/import-and-import-from]
from chia.consensus.block_creation import unfinished_block_to_full_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import Blockchain, ReceiveBlockResult, StateChangeSummary
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.consensus.pot_iterations import calculate_sp_iters
from chia.full_node.block_store import BlockStore
from chia.full_node.hint_management import get_hints_and_subscription_coin_ids
from chia.full_node.lock_queue import LockQueue, LockClient
from chia.full_node.bundle_tools import detect_potential_template_generator
from chia.full_node.coin_store import CoinStore
from chia.full_node.full_node_store import FullNodeStore, FullNodeStorePeakResult
from chia.full_node.hint_store import HintStore
from chia.full_node.mempool_manager import MempoolManager
from chia.full_node.signage_point import SignagePoint
from chia.full_node.sync_store import SyncStore
from chia.full_node.weight_proof import WeightProofHandler
from chia.protocols import farmer_protocol, full_node_protocol, timelord_protocol, wallet_protocol
from chia.protocols.full_node_protocol import (
    RequestBlocks,
    RespondBlock,
    RespondBlocks,
    RespondSignagePoint,
)
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import CoinState, CoinStateUpdate
from chia.server.node_discovery import FullNodePeers
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.peer_store_resolver import PeerStoreResolver
from chia.server.server import ChiaServer
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import CompressibleVDFField, VDFInfo, VDFProof
from chia.types.coin_record import CoinRecord
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator
from chia.types.header_block import HeaderBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.types.transaction_queue_entry import TransactionQueueEntry
from chia.types.unfinished_block import UnfinishedBlock
from chia.util import cached_bls
from chia.util.bech32m import encode_puzzle_hash
from chia.util.check_fork_next_block import check_fork_next_block
from chia.util.condition_tools import pkm_pairs
from chia.util.config import PEER_DB_PATH_KEY_DEPRECATED, process_config_start_method
from chia.util.db_wrapper import DBWrapper2, manage_connection
from chia.util.errors import ConsensusError, Err, ValidationError
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.path import path_from_root
from chia.util.safe_cancel_task import cancel_task_safe
from chia.util.profiler import profile_task
from chia.util.memory_profiler import mem_profile_task
from chia.util.db_synchronous import db_synchronous_on
from chia.util.db_version import lookup_db_version, set_db_version_async


# This is the result of calling peak_post_processing, which is then fed into peak_post_processing_2
@dataclasses.dataclass
class PeakPostProcessingResult:
    mempool_peak_result: List[Tuple[SpendBundle, NPCResult, bytes32]]  # The result of calling MempoolManager.new_peak
    fns_peak_result: FullNodeStorePeakResult  # The result of calling FullNodeStore.new_peak
    hints: List[Tuple[bytes32, bytes]]  # The hints added to the DB
    lookup_coin_ids: List[bytes32]  # The coin IDs that we need to look up to notify wallets of changes


class FullNode:
    _segment_task: Optional[asyncio.Task[None]]
    initialized: bool
    root_path: Path
    config: Dict[str, Any]
    _server: Optional[ChiaServer]
    _shut_down: bool
    constants: ConsensusConstants
    pow_creation: Dict[bytes32, asyncio.Event]
    state_changed_callback: Optional[Callable[[str, Optional[Dict[str, Any]]], None]]
    full_node_peers: Optional[FullNodePeers]
    sync_store: Any
    signage_point_times: List[float]
    full_node_store: FullNodeStore
    uncompact_task: Optional[asyncio.Task[None]]
    compact_vdf_requests: Set[bytes32]
    log: logging.Logger
    multiprocessing_context: Optional[BaseContext]
    _ui_tasks: Set[asyncio.Task[None]]
    db_path: Path
    # TODO: use NewType all over to describe these various uses of the same types
    # Puzzle Hash : Set[Peer ID]
    coin_subscriptions: Dict[bytes32, Set[bytes32]]
    # Puzzle Hash : Set[Peer ID]
    ph_subscriptions: Dict[bytes32, Set[bytes32]]
    # Peer ID: Set[Coin ids]
    peer_coin_ids: Dict[bytes32, Set[bytes32]]
    # Peer ID: Set[puzzle_hash]
    peer_puzzle_hash: Dict[bytes32, Set[bytes32]]
    # Peer ID: subscription count
    peer_sub_counter: Dict[bytes32, int]
    _transaction_queue_task: Optional[asyncio.Task[None]]
    simulator_transaction_callback: Optional[Callable[[bytes32], Awaitable[None]]]
    _sync_task: Optional[asyncio.Task[None]]
    _transaction_queue: Optional[asyncio.PriorityQueue[Tuple[int, TransactionQueueEntry]]]
    _compact_vdf_sem: Optional[asyncio.Semaphore]
    _new_peak_sem: Optional[asyncio.Semaphore]
    _respond_transaction_semaphore: Optional[asyncio.Semaphore]
    _db_wrapper: Optional[DBWrapper2]
    _hint_store: Optional[HintStore]
    transaction_responses: List[Tuple[bytes32, MempoolInclusionStatus, Optional[Err]]]
    _block_store: Optional[BlockStore]
    _coin_store: Optional[CoinStore]
    _mempool_manager: Optional[MempoolManager]
    _init_weight_proof: Optional[asyncio.Task[None]]
    _blockchain: Optional[Blockchain]
    _timelord_lock: Optional[asyncio.Lock]
    weight_proof_handler: Optional[WeightProofHandler]
    _blockchain_lock_queue: Optional[LockQueue]
    _maybe_blockchain_lock_high_priority: Optional[LockClient]
    _maybe_blockchain_lock_low_priority: Optional[LockClient]

    @property
    def server(self) -> ChiaServer:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    def __init__(
        self,
        config: Dict[str, Any],
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = __name__,
    ) -> None:
        self._segment_task = None
        self.initialized = False
        self.root_path = root_path
        self.config = config
        self._server = None
        self._shut_down = False  # Set to true to close all infinite loops
        self.constants = consensus_constants
        self.pow_creation = {}
        self.state_changed_callback = None
        self.full_node_peers = None
        self.sync_store = None
        self.signage_point_times = [time.time() for _ in range(self.constants.NUM_SPS_SUB_SLOT)]
        self.full_node_store = FullNodeStore(self.constants)
        self.uncompact_task = None
        self.compact_vdf_requests = set()
        self.log = logging.getLogger(name)

        # TODO: Logging isn't setup yet so the log entries related to parsing the
        #       config would end up on stdout if handled here.
        self.multiprocessing_context = None

        self._ui_tasks = set()

        db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
        self.db_path = path_from_root(root_path, db_path_replaced)
        self.coin_subscriptions = {}
        self.ph_subscriptions = {}
        self.peer_coin_ids = {}
        self.peer_puzzle_hash = {}
        self.peer_sub_counter = {}
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._transaction_queue_task = None
        self.simulator_transaction_callback = None

        self._sync_task = None
        self._transaction_queue = None
        self._compact_vdf_sem = None
        self._new_peak_sem = None
        self._respond_transaction_semaphore = None
        self._db_wrapper = None
        self._hint_store = None
        self.transaction_responses = []
        self._block_store = None
        self._coin_store = None
        self._mempool_manager = None
        self._init_weight_proof = None
        self._blockchain = None
        self._timelord_lock = None
        self.weight_proof_handler = None
        self._blockchain_lock_queue = None
        self._maybe_blockchain_lock_high_priority = None
        self._maybe_blockchain_lock_low_priority = None

    @property
    def block_store(self) -> BlockStore:
        assert self._block_store is not None
        return self._block_store

    @property
    def _blockchain_lock_high_priority(self) -> LockClient:
        assert self._maybe_blockchain_lock_high_priority is not None
        return self._maybe_blockchain_lock_high_priority

    @property
    def _blockchain_lock_low_priority(self) -> LockClient:
        assert self._maybe_blockchain_lock_low_priority is not None
        return self._maybe_blockchain_lock_low_priority

    @property
    def timelord_lock(self) -> asyncio.Lock:
        assert self._timelord_lock is not None
        return self._timelord_lock

    @property
    def mempool_manager(self) -> MempoolManager:
        assert self._mempool_manager is not None
        return self._mempool_manager

    @property
    def blockchain(self) -> Blockchain:
        assert self._blockchain is not None
        return self._blockchain

    @property
    def coin_store(self) -> CoinStore:
        assert self._coin_store is not None
        return self._coin_store

    @property
    def respond_transaction_semaphore(self) -> asyncio.Semaphore:
        assert self._respond_transaction_semaphore is not None
        return self._respond_transaction_semaphore

    @property
    def transaction_queue(self) -> asyncio.PriorityQueue[Tuple[int, TransactionQueueEntry]]:
        assert self._transaction_queue is not None
        return self._transaction_queue

    @property
    def db_wrapper(self) -> DBWrapper2:
        assert self._db_wrapper is not None
        return self._db_wrapper

    @property
    def hint_store(self) -> HintStore:
        assert self._hint_store is not None
        return self._hint_store

    @property
    def new_peak_sem(self) -> asyncio.Semaphore:
        assert self._new_peak_sem is not None
        return self._new_peak_sem

    @property
    def compact_vdf_sem(self) -> asyncio.Semaphore:
        assert self._compact_vdf_sem is not None
        return self._compact_vdf_sem

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        connections = self.server.get_connections(request_node_type)
        con_info: List[Dict[str, Any]] = []
        if self.sync_store is not None:
            peak_store = self.sync_store.peer_to_peak
        else:
            peak_store = None
        for con in connections:
            if peak_store is not None and con.peer_node_id in peak_store:
                peak_hash, peak_height, peak_weight = peak_store[con.peer_node_id]
            else:
                peak_height = None
                peak_hash = None
                peak_weight = None
            con_dict: Dict[str, Any] = {
                "type": con.connection_type,
                "local_port": con.local_port,
                "peer_host": con.peer_host,
                "peer_port": con.peer_port,
                "peer_server_port": con.peer_server_port,
                "node_id": con.peer_node_id,
                "creation_time": con.creation_time,
                "bytes_read": con.bytes_read,
                "bytes_written": con.bytes_written,
                "last_message_time": con.last_message_time,
                "peak_height": peak_height,
                "peak_weight": peak_weight,
                "peak_hash": peak_hash,
            }
            con_info.append(con_dict)

        return con_info

    def _set_state_changed_callback(self, callback: Callable[..., Any]) -> None:
        self.state_changed_callback = callback

    async def _start(self) -> None:
        self._timelord_lock = asyncio.Lock()
        self._compact_vdf_sem = asyncio.Semaphore(4)

        # We don't want to run too many concurrent new_peak instances, because it would fetch the same block from
        # multiple peers and re-validate.
        self._new_peak_sem = asyncio.Semaphore(2)

        # These many respond_transaction tasks can be active at any point in time
        self._respond_transaction_semaphore = asyncio.Semaphore(200)
        # create the store (db) and full node instance
        # TODO: is this standardized and thus able to be handled by DBWrapper2?
        async with manage_connection(self.db_path) as db_connection:
            db_version = await lookup_db_version(db_connection)
        self.log.info(f"using blockchain database {self.db_path}, which is version {db_version}")

        sql_log_path: Optional[Path] = None
        if self.config.get("log_sqlite_cmds", False):
            sql_log_path = path_from_root(self.root_path, "log/sql.log")
            self.log.info(f"logging SQL commands to {sql_log_path}")

        db_sync = db_synchronous_on(self.config.get("db_sync", "auto"))
        self.log.info(f"opening blockchain DB: synchronous={db_sync}")

        self._db_wrapper = await DBWrapper2.create(
            self.db_path,
            db_version=db_version,
            reader_count=4,
            log_path=sql_log_path,
            synchronous=db_sync,
        )

        if self.db_wrapper.db_version != 2:
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='full_blocks'"
                ) as cur:
                    if len(list(await cur.fetchall())) == 0:
                        try:
                            # this is a new DB file. Make it v2
                            async with self.db_wrapper.writer_maybe_transaction() as w_conn:
                                await set_db_version_async(w_conn, 2)
                                self.db_wrapper.db_version = 2
                                self.log.info("blockchain database is empty, configuring as v2")
                        except sqlite3.OperationalError:
                            # it could be a database created with "chia init", which is
                            # empty except it has the database_version table
                            pass

        self._block_store = await BlockStore.create(self.db_wrapper)
        self.sync_store = SyncStore()
        self._hint_store = await HintStore.create(self.db_wrapper)
        self._coin_store = await CoinStore.create(self.db_wrapper)
        self.log.info("Initializing blockchain from disk")
        start_time = time.time()
        reserved_cores = self.config.get("reserved_cores", 0)
        single_threaded = self.config.get("single_threaded", False)
        multiprocessing_start_method = process_config_start_method(config=self.config, log=self.log)
        self.multiprocessing_context = multiprocessing.get_context(method=multiprocessing_start_method)
        self._blockchain = await Blockchain.create(
            coin_store=self.coin_store,
            block_store=self.block_store,
            consensus_constants=self.constants,
            blockchain_dir=self.db_path.parent,
            reserved_cores=reserved_cores,
            multiprocessing_context=self.multiprocessing_context,
            single_threaded=single_threaded,
        )

        self._mempool_manager = MempoolManager(
            coin_store=self.coin_store,
            consensus_constants=self.constants,
            multiprocessing_context=self.multiprocessing_context,
            single_threaded=single_threaded,
        )

        # Blocks are validated under high priority, and transactions under low priority. This guarantees blocks will
        # be validated first.
        blockchain_lock_queue = LockQueue(self.blockchain.lock)
        self._blockchain_lock_queue = blockchain_lock_queue
        self._maybe_blockchain_lock_high_priority = LockClient(0, blockchain_lock_queue)
        self._maybe_blockchain_lock_low_priority = LockClient(1, blockchain_lock_queue)

        # Transactions go into this queue from the server, and get sent to respond_transaction
        self._transaction_queue = asyncio.PriorityQueue(10000)
        self._transaction_queue_task: asyncio.Task[None] = asyncio.create_task(self._handle_transactions())
        self.transaction_responses = []

        self._init_weight_proof = asyncio.create_task(self.initialize_weight_proof())

        if self.config.get("enable_profiler", False):
            asyncio.create_task(profile_task(self.root_path, "node", self.log))

        if self.config.get("enable_memory_profiler", False):
            asyncio.create_task(mem_profile_task(self.root_path, "node", self.log))

        time_taken = time.time() - start_time
        peak: Optional[BlockRecord] = self.blockchain.get_peak()
        if peak is None:
            self.log.info(f"Initialized with empty blockchain time taken: {int(time_taken)}s")
            num_unspent = await self.coin_store.num_unspent()
            if num_unspent > 0:
                self.log.error(
                    f"Inconsistent blockchain DB file! Could not find peak block but found {num_unspent} coins! "
                    "This is a fatal error. The blockchain database may be corrupt"
                )
                raise RuntimeError("corrupt blockchain DB")
        else:
            self.log.info(
                f"Blockchain initialized to peak {peak.header_hash} height"
                f" {peak.height}, "
                f"time taken: {int(time_taken)}s"
            )
            async with self._blockchain_lock_high_priority:
                pending_tx = await self.mempool_manager.new_peak(peak, None)
            assert len(pending_tx) == 0  # no pending transactions when starting up

            full_peak: Optional[FullBlock] = await self.blockchain.get_full_peak()
            assert full_peak is not None
            state_change_summary = StateChangeSummary(peak, uint32(max(peak.height - 1, 0)), [], [], [])
            ppp_result: PeakPostProcessingResult = await self.peak_post_processing(
                full_peak, state_change_summary, None
            )
            await self.peak_post_processing_2(full_peak, None, state_change_summary, ppp_result)
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

    async def _handle_one_transaction(self, entry: TransactionQueueEntry) -> None:
        peer = entry.peer
        try:
            inc_status, err = await self.respond_transaction(entry.transaction, entry.spend_name, peer, entry.test)
            self.transaction_responses.append((entry.spend_name, inc_status, err))
            if len(self.transaction_responses) > 50:
                self.transaction_responses = self.transaction_responses[1:]
        except asyncio.CancelledError:
            error_stack = traceback.format_exc()
            self.log.debug(f"Cancelling _handle_one_transaction, closing: {error_stack}")
        except Exception:
            error_stack = traceback.format_exc()
            self.log.error(f"Error in _handle_one_transaction, closing: {error_stack}")
            if peer is not None:
                await peer.close()
        finally:
            self.respond_transaction_semaphore.release()

    async def _handle_transactions(self) -> None:
        try:
            while not self._shut_down:
                # We use a semaphore to make sure we don't send more than 200 concurrent calls of respond_transaction.
                # However, doing them one at a time would be slow, because they get sent to other processes.
                await self.respond_transaction_semaphore.acquire()
                item: TransactionQueueEntry = (await self.transaction_queue.get())[1]
                asyncio.create_task(self._handle_one_transaction(item))
        except asyncio.CancelledError:
            raise

    async def initialize_weight_proof(self) -> None:
        self.weight_proof_handler = WeightProofHandler(
            constants=self.constants,
            blockchain=self.blockchain,
            multiprocessing_context=self.multiprocessing_context,
        )
        peak = self.blockchain.get_peak()
        if peak is not None:
            await self.weight_proof_handler.create_sub_epoch_segments()

    def set_server(self, server: ChiaServer) -> None:
        self._server = server
        dns_servers: List[str] = []
        network_name = self.config["selected_network"]
        try:
            default_port = self.config["network_overrides"]["config"][network_name]["default_full_node_port"]
        except Exception:
            self.log.info("Default port field not found in config.")
            default_port = None
        if "dns_servers" in self.config:
            dns_servers = self.config["dns_servers"]
        elif self.config["port"] == 8444:
            # If `dns_servers` misses from the `config`, hardcode it if we're running mainnet.
            dns_servers.append("dns-introducer.chia.net")
        try:
            self.full_node_peers = FullNodePeers(
                self.server,
                self.config["target_peer_count"] - self.config["target_outbound_peer_count"],
                self.config["target_outbound_peer_count"],
                PeerStoreResolver(
                    self.root_path,
                    self.config,
                    selected_network=network_name,
                    peers_file_path_key="peers_file_path",
                    legacy_peer_db_path_key=PEER_DB_PATH_KEY_DEPRECATED,
                    default_peers_file_path="db/peers.dat",
                ),
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

    def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]] = None) -> None:
        if self.state_changed_callback is not None:
            self.state_changed_callback(change, change_data)

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
                async with self._blockchain_lock_high_priority:
                    state_change_summary: Optional[StateChangeSummary]
                    success, state_change_summary = await self.receive_block_batch(response.blocks, peer, None)
                    if not success:
                        raise ValueError(f"Error short batch syncing, failed to validate blocks {height}-{end_height}")
                    if state_change_summary is not None:
                        try:
                            peak_fb: Optional[FullBlock] = await self.blockchain.get_full_peak()
                            assert peak_fb is not None
                            ppp_result: PeakPostProcessingResult = await self.peak_post_processing(
                                peak_fb,
                                state_change_summary,
                                peer,
                            )
                            await self.peak_post_processing_2(peak_fb, peer, state_change_summary, ppp_result)
                        except Exception:
                            # Still do post processing after cancel (or exception)
                            peak_fb = await self.blockchain.get_full_peak()
                            assert peak_fb is not None
                            await self.peak_post_processing(peak_fb, state_change_summary, peer)
                            raise
                        finally:
                            self.log.info(f"Added blocks {height}-{end_height}")
        except (asyncio.CancelledError, Exception):
            self.sync_store.batch_syncing.remove(peer.peer_node_id)
            raise
        self.sync_store.batch_syncing.remove(peer.peer_node_id)
        return True

    async def short_sync_backtrack(
        self, peer: ws.WSChiaConnection, peak_height: uint32, target_height: uint32, target_unf_hash: bytes32
    ) -> bool:
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
                    raise ValueError(f"Failed to fetch block {curr_height} from {peer.get_peer_logging()}, timed out")
                if curr is None or not isinstance(curr, full_node_protocol.RespondBlock):
                    raise ValueError(
                        f"Failed to fetch block {curr_height} from {peer.get_peer_logging()}, wrong type {type(curr)}"
                    )
                responses.append(curr)
                if self.blockchain.contains_block(curr.block.prev_header_hash) or curr_height == 0:
                    found_fork_point = True
                    break
                curr_height -= 1
            if found_fork_point:
                for response in reversed(responses):
                    await self.respond_block(response, peer)
        except (asyncio.CancelledError, Exception):
            self.sync_store.backtrack_syncing[peer.peer_node_id] -= 1
            raise

        self.sync_store.backtrack_syncing[peer.peer_node_id] -= 1
        return found_fork_point

    async def _refresh_ui_connections(self, sleep_before: float = 0) -> None:
        if sleep_before > 0:
            await asyncio.sleep(sleep_before)
        self._state_changed("peer_changed_peak")

    async def new_peak(self, request: full_node_protocol.NewPeak, peer: ws.WSChiaConnection) -> None:
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
        self, peak_block: Optional[FullBlock] = None, peer: Optional[ws.WSChiaConnection] = None
    ) -> None:
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
        if "simulator" in str(self.config.get("selected_network")):
            return True  # sim is always synced because it has no peers
        curr: Optional[BlockRecord] = self.blockchain.get_peak()
        if curr is None:
            return False

        while curr is not None and not curr.is_transaction_block:
            curr = self.blockchain.try_block_record(curr.prev_hash)

        now = time.time()
        if (
            curr is None
            or curr.timestamp is None
            or curr.timestamp < uint64(int(now - 60 * 7))
            or self.sync_store.get_sync_mode()
        ):
            return False
        else:
            return True

    async def on_connect(self, connection: ws.WSChiaConnection) -> None:
        """
        Whenever we connect to another node / wallet, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """

        self._state_changed("add_connection")
        self._state_changed("sync_mode")
        if self.full_node_peers is not None:
            asyncio.create_task(self.full_node_peers.on_connect(connection))

        if self.initialized is False:
            return None

        if connection.connection_type is NodeType.FULL_NODE:
            # Send filter to node and request mempool items that are not in it (Only if we are currently synced)
            synced = await self.synced()
            peak_height = self.blockchain.get_peak_height()
            if synced and peak_height is not None:
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

    def on_disconnect(self, connection: ws.WSChiaConnection) -> None:
        self.log.info(f"peer disconnected {connection.get_peer_logging()}")
        self._state_changed("close_connection")
        self._state_changed("sync_mode")
        if self.sync_store is not None:
            self.sync_store.peer_disconnected(connection.peer_node_id)
        self.remove_subscriptions(connection)

    def remove_subscriptions(self, peer: ws.WSChiaConnection) -> None:
        # Remove all ph | coin id subscription for this peer
        node_id = peer.peer_node_id
        if node_id in self.peer_puzzle_hash:
            puzzle_hashes = self.peer_puzzle_hash[node_id]
            for ph in puzzle_hashes:
                if ph in self.ph_subscriptions:
                    if node_id in self.ph_subscriptions[ph]:
                        self.ph_subscriptions[ph].remove(node_id)

        if node_id in self.peer_coin_ids:
            coin_ids = self.peer_coin_ids[node_id]
            for coin_id in coin_ids:
                if coin_id in self.coin_subscriptions:
                    if node_id in self.coin_subscriptions[coin_id]:
                        self.coin_subscriptions[coin_id].remove(node_id)

        if peer.peer_node_id in self.peer_sub_counter:
            self.peer_sub_counter.pop(peer.peer_node_id)

    def _num_needed_peers(self) -> int:
        assert self.server.all_connections is not None
        diff: int = int(self.config["target_peer_count"]) - len(self.server.all_connections)
        return diff if diff >= 0 else 0

    def _close(self) -> None:
        self._shut_down = True
        if self._init_weight_proof is not None:
            self._init_weight_proof.cancel()

        # blockchain is created in _start and in certain cases it may not exist here during _close
        if self._blockchain is not None:
            self.blockchain.shut_down()
        # same for mempool_manager
        if self._mempool_manager is not None:
            self.mempool_manager.shut_down()

        if self.full_node_peers is not None:
            asyncio.create_task(self.full_node_peers.close())
        if self.uncompact_task is not None:
            self.uncompact_task.cancel()
        if self._transaction_queue_task is not None:
            self._transaction_queue_task.cancel()
        if self._blockchain_lock_queue is not None:
            self._blockchain_lock_queue.close()
        cancel_task_safe(task=self._sync_task, log=self.log)

    async def _await_closed(self) -> None:
        for task_id, task in list(self.full_node_store.tx_fetch_tasks.items()):
            cancel_task_safe(task, self.log)
        await self.db_wrapper.close()
        if self._init_weight_proof is not None:
            await asyncio.wait([self._init_weight_proof])
        if self._blockchain_lock_queue is not None:
            await self._blockchain_lock_queue.await_closed()
        if self._sync_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._sync_task

    async def _sync(self) -> None:
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
                    continue
                break

            self.log.info(f"Collected a total of {len(peaks)} peaks.")

            # Based on responses from peers about the current peaks, see which peak is the heaviest
            # (similar to longest chain rule).
            target_peak = self.sync_store.get_heaviest_peak()

            if target_peak is None:
                raise RuntimeError("Not performing sync, no peaks collected")
            heaviest_peak_hash, heaviest_peak_height, heaviest_peak_weight = target_peak
            self.sync_store.set_peak_target(heaviest_peak_hash, heaviest_peak_height)

            self.log.info(f"Selected peak {heaviest_peak_height}, {heaviest_peak_hash}")
            # Check which peers are updated to this height

            peers: List[bytes32] = []
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
            peers_with_peak: List[ws.WSChiaConnection] = [
                c for c in self.server.all_connections.values() if c.peer_node_id in peer_ids
            ]

            # Request weight proof from a random peer
            self.log.info(f"Total of {len(peers_with_peak)} peers with peak {heaviest_peak_height}")
            weight_proof_peer: ws.WSChiaConnection = random.choice(peers_with_peak)
            self.log.info(
                f"Requesting weight proof from peer {weight_proof_peer.peer_host} up to height"
                f" {heaviest_peak_height}"
            )
            cur_peak: Optional[BlockRecord] = self.blockchain.get_peak()
            if cur_peak is not None and heaviest_peak_weight <= cur_peak.weight:
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
            async with self._blockchain_lock_high_priority:
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
        fork_point_height: uint32,
        target_peak_sb_height: uint32,
        peak_hash: bytes32,
        summaries: List[SubEpochSummary],
    ) -> None:
        buffer_size = 4
        self.log.info(f"Start syncing from fork point at {fork_point_height} up to {target_peak_sb_height}")
        peers_with_peak: List[ws.WSChiaConnection] = self.get_peers_with_peak(peak_hash)
        fork_point_height = await check_fork_next_block(
            self.blockchain, fork_point_height, peers_with_peak, node_next_block_check
        )
        batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS

        async def fetch_block_batches(
            batch_queue: asyncio.Queue[Optional[Tuple[ws.WSChiaConnection, List[FullBlock]]]]
        ) -> None:
            start_height, end_height = 0, 0
            new_peers_with_peak: List[ws.WSChiaConnection] = peers_with_peak[:]
            try:
                for start_height in range(fork_point_height, target_peak_sb_height, batch_size):
                    end_height = min(target_peak_sb_height, start_height + batch_size)
                    request = RequestBlocks(uint32(start_height), uint32(end_height), True)
                    fetched = False
                    for peer in random.sample(new_peers_with_peak, len(new_peers_with_peak)):
                        if peer.closed:
                            peers_with_peak.remove(peer)
                            continue
                        response = await peer.request_blocks(request, timeout=30)
                        if response is None:
                            await peer.close()
                            peers_with_peak.remove(peer)
                        elif isinstance(response, RespondBlocks):
                            await batch_queue.put((peer, response.blocks))
                            fetched = True
                            break
                    if fetched is False:
                        self.log.error(f"failed fetching {start_height} to {end_height} from peers")
                        await batch_queue.put(None)
                        return
                    if self.sync_store.peers_changed.is_set():
                        new_peers_with_peak = self.get_peers_with_peak(peak_hash)
                        self.sync_store.peers_changed.clear()
            except Exception as e:
                self.log.error(f"Exception fetching {start_height} to {end_height} from peer {e}")
            finally:
                # finished signal with None
                await batch_queue.put(None)

        async def validate_block_batches(
            inner_batch_queue: asyncio.Queue[Optional[Tuple[ws.WSChiaConnection, List[FullBlock]]]]
        ) -> None:
            advanced_peak: bool = False
            while True:
                res: Optional[Tuple[ws.WSChiaConnection, List[FullBlock]]] = await inner_batch_queue.get()
                if res is None:
                    self.log.debug("done fetching blocks")
                    return None
                peer, blocks = res
                start_height = blocks[0].height
                end_height = blocks[-1].height
                success, state_change_summary = await self.receive_block_batch(
                    blocks, peer, None if advanced_peak else uint32(fork_point_height), summaries
                )
                if success is False:
                    if peer in peers_with_peak:
                        peers_with_peak.remove(peer)
                    await peer.close(600)
                    raise ValueError(f"Failed to validate block batch {start_height} to {end_height}")
                self.log.info(f"Added blocks {start_height} to {end_height}")
                peak: Optional[BlockRecord] = self.blockchain.get_peak()
                if state_change_summary is not None:
                    advanced_peak = True
                    assert peak is not None
                    # Hints must be added to the DB. The other post-processing tasks are not required when syncing
                    hints_to_add, lookup_coin_ids = get_hints_and_subscription_coin_ids(
                        state_change_summary, self.coin_subscriptions, self.ph_subscriptions
                    )
                    await self.hint_store.add_hints(hints_to_add)
                    await self.update_wallets(state_change_summary, hints_to_add, lookup_coin_ids)
                await self.send_peak_to_wallets()
                self.blockchain.clean_block_record(end_height - self.constants.BLOCKS_CACHE_SIZE)

        batch_queue_input: asyncio.Queue[Optional[Tuple[ws.WSChiaConnection, List[FullBlock]]]] = asyncio.Queue(
            maxsize=buffer_size
        )
        fetch_task = asyncio.Task(fetch_block_batches(batch_queue_input))
        validate_task = asyncio.Task(validate_block_batches(batch_queue_input))
        try:
            await asyncio.gather(fetch_task, validate_task)
        except Exception as e:
            assert validate_task.done()
            fetch_task.cancel()  # no need to cancel validate_task, if we end up here validate_task is already done
            self.log.error(f"sync from fork point failed err: {e}")

    async def send_peak_to_wallets(self) -> None:
        peak = self.blockchain.get_peak()
        assert peak is not None
        msg = make_msg(
            ProtocolMessageTypes.new_peak_wallet,
            wallet_protocol.NewPeakWallet(
                peak.header_hash, peak.height, peak.weight, uint32(max(peak.height - 1, uint32(0)))
            ),
        )
        await self.server.send_to_all([msg], NodeType.WALLET)

    def get_peers_with_peak(self, peak_hash: bytes32) -> List[ws.WSChiaConnection]:
        peer_ids: Set[bytes32] = self.sync_store.get_peers_that_have_peak([peak_hash])
        if len(peer_ids) == 0:
            self.log.warning(f"Not syncing, no peers with header_hash {peak_hash} ")
            return []
        return [c for c in self.server.all_connections.values() if c.peer_node_id in peer_ids]

    async def update_wallets(
        self,
        state_change_summary: StateChangeSummary,
        hints: List[Tuple[bytes32, bytes]],
        lookup_coin_ids: List[bytes32],
    ) -> None:
        # Looks up coin records in DB for the coins that wallets are interested in
        new_states: List[CoinRecord] = await self.coin_store.get_coin_records(list(lookup_coin_ids))

        # Re-arrange to a map, and filter out any non-ph sized hint
        coin_id_to_ph_hint: Dict[bytes32, bytes32] = {
            coin_id: bytes32(hint) for coin_id, hint in hints if len(hint) == 32
        }

        changes_for_peer: Dict[bytes32, Set[CoinState]] = {}
        for coin_record in state_change_summary.rolled_back_records + [s for s in new_states if s is not None]:
            cr_name: bytes32 = coin_record.name
            for peer in self.coin_subscriptions.get(cr_name, []):
                if peer not in changes_for_peer:
                    changes_for_peer[peer] = set()
                changes_for_peer[peer].add(coin_record.coin_state)

            for peer in self.ph_subscriptions.get(coin_record.coin.puzzle_hash, []):
                if peer not in changes_for_peer:
                    changes_for_peer[peer] = set()
                changes_for_peer[peer].add(coin_record.coin_state)

            if cr_name in coin_id_to_ph_hint:
                for peer in self.ph_subscriptions.get(coin_id_to_ph_hint[cr_name], []):
                    if peer not in changes_for_peer:
                        changes_for_peer[peer] = set()
                    changes_for_peer[peer].add(coin_record.coin_state)

        for peer, changes in changes_for_peer.items():
            if peer not in self.server.all_connections:
                continue
            ws_peer: ws.WSChiaConnection = self.server.all_connections[peer]
            state = CoinStateUpdate(
                state_change_summary.peak.height,
                state_change_summary.fork_height,
                state_change_summary.peak.header_hash,
                list(changes),
            )
            msg = make_msg(ProtocolMessageTypes.coin_state_update, state)
            await ws_peer.send_message(msg)

    async def receive_block_batch(
        self,
        all_blocks: List[FullBlock],
        peer: ws.WSChiaConnection,
        fork_point: Optional[uint32],
        wp_summaries: Optional[List[SubEpochSummary]] = None,
    ) -> Tuple[bool, Optional[StateChangeSummary]]:
        # Precondition: All blocks must be contiguous blocks, index i+1 must be the parent of index i
        # Returns a bool for success, as well as a StateChangeSummary if the peak was advanced

        blocks_to_validate: List[FullBlock] = []
        for i, block in enumerate(all_blocks):
            if not self.blockchain.contains_block(block.header_hash):
                blocks_to_validate = all_blocks[i:]
                break
        if len(blocks_to_validate) == 0:
            return True, None

        # Validates signatures in multiprocessing since they take a while, and we don't have cached transactions
        # for these blocks (unlike during normal operation where we validate one at a time)
        pre_validate_start = time.monotonic()
        pre_validation_results: List[PreValidationResult] = await self.blockchain.pre_validate_blocks_multiprocessing(
            blocks_to_validate, {}, wp_summaries=wp_summaries, validate_signatures=True
        )
        pre_validate_end = time.monotonic()
        pre_validate_time = pre_validate_end - pre_validate_start

        self.log.log(
            logging.WARNING if pre_validate_time > 10 else logging.DEBUG,
            f"Block pre-validation time: {pre_validate_end - pre_validate_start:0.2f} seconds "
            f"({len(blocks_to_validate)} blocks, start height: {blocks_to_validate[0].height})",
        )
        for i, block in enumerate(blocks_to_validate):
            if pre_validation_results[i].error is not None:
                self.log.error(
                    f"Invalid block from peer: {peer.get_peer_logging()} {Err(pre_validation_results[i].error)}"
                )
                return False, None

        agg_state_change_summary: Optional[StateChangeSummary] = None

        for i, block in enumerate(blocks_to_validate):
            assert pre_validation_results[i].required_iters is not None
            state_change_summary: Optional[StateChangeSummary]
            advanced_peak = agg_state_change_summary is not None
            result, error, state_change_summary = await self.blockchain.receive_block(
                block, pre_validation_results[i], None if advanced_peak else fork_point
            )

            if result == ReceiveBlockResult.NEW_PEAK:
                assert state_change_summary is not None
                # Since all blocks are contiguous, we can simply append the rollback changes and npc results
                if agg_state_change_summary is None:
                    agg_state_change_summary = state_change_summary
                else:
                    # Keeps the old, original fork_height, since the next blocks will have fork height h-1
                    # Groups up all state changes into one
                    agg_state_change_summary = StateChangeSummary(
                        state_change_summary.peak,
                        agg_state_change_summary.fork_height,
                        agg_state_change_summary.rolled_back_records + state_change_summary.rolled_back_records,
                        agg_state_change_summary.new_npc_results + state_change_summary.new_npc_results,
                        agg_state_change_summary.new_rewards + state_change_summary.new_rewards,
                    )
            elif result == ReceiveBlockResult.INVALID_BLOCK or result == ReceiveBlockResult.DISCONNECTED_BLOCK:
                if error is not None:
                    self.log.error(f"Error: {error}, Invalid block from peer: {peer.get_peer_logging()} ")
                return False, agg_state_change_summary
            block_record = self.blockchain.block_record(block.header_hash)
            if block_record.sub_epoch_summary_included is not None:
                if self.weight_proof_handler is not None:
                    await self.weight_proof_handler.create_prev_sub_epoch_segments()
        if agg_state_change_summary is not None:
            self._state_changed("new_peak")
            self.log.debug(
                f"Total time for {len(blocks_to_validate)} blocks: {time.time() - pre_validate_start}, "
                f"advanced: True"
            )
        return True, agg_state_change_summary

    async def _finish_sync(self) -> None:
        """
        Finalize sync by setting sync mode to False, clearing all sync information, and adding any final
        blocks that we have finalized recently.
        """
        self.log.info("long sync done")
        self.sync_store.set_long_sync(False)
        self.sync_store.set_sync_mode(False)
        self._state_changed("sync_mode")
        if self._server is None:
            return None

        async with self._blockchain_lock_high_priority:
            await self.sync_store.clear_sync_info()

            peak: Optional[BlockRecord] = self.blockchain.get_peak()
            peak_fb: Optional[FullBlock] = await self.blockchain.get_full_peak()
            if peak_fb is not None:
                assert peak is not None
                state_change_summary = StateChangeSummary(peak, uint32(max(peak.height - 1, 0)), [], [], [])
                ppp_result: PeakPostProcessingResult = await self.peak_post_processing(
                    peak_fb, state_change_summary, None
                )
                await self.peak_post_processing_2(peak_fb, None, state_change_summary, ppp_result)

        if peak is not None and self.weight_proof_handler is not None:
            await self.weight_proof_handler.get_proof_of_weight(peak.header_hash)
            self._state_changed("block")

    def has_valid_pool_sig(self, block: Union[UnfinishedBlock, FullBlock]) -> bool:
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
        peer: ws.WSChiaConnection,
        ip_sub_slot: Optional[EndOfSubSlotBundle],
    ) -> None:
        self.log.info(
            f"⏲️  Finished signage point {request.index_from_challenge}/"
            f"{self.constants.NUM_SPS_SUB_SLOT}: "
            f"CC: {request.challenge_chain_vdf.output.get_hash()} "
            f"RC: {request.reward_chain_vdf.output.get_hash()} "
        )
        self.signage_point_times[request.index_from_challenge] = time.time()
        sub_slot_tuple = self.full_node_store.get_sub_slot(request.challenge_chain_vdf.challenge)
        prev_challenge: Optional[bytes32]
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

        self._state_changed("signage_point", {"broadcast_farmer": broadcast_farmer})

    async def peak_post_processing(
        self,
        block: FullBlock,
        state_change_summary: StateChangeSummary,
        peer: Optional[ws.WSChiaConnection],
    ) -> PeakPostProcessingResult:
        """
        Must be called under self.blockchain.lock. This updates the internal state of the full node with the
        latest peak information. It also notifies peers about the new peak.
        """

        record = state_change_summary.peak
        difficulty = self.blockchain.get_next_difficulty(record.header_hash, False)
        sub_slot_iters = self.blockchain.get_next_slot_iters(record.header_hash, False)

        self.log.info(
            f"🌱 Updated peak to height {record.height}, weight {record.weight}, "
            f"hh {record.header_hash}, "
            f"forked at {state_change_summary.fork_height}, rh: {record.reward_infusion_new_challenge}, "
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

        if (
            self.full_node_store.previous_generator is not None
            and state_change_summary.fork_height < self.full_node_store.previous_generator.block_height
        ):
            self.full_node_store.previous_generator = None

        hints_to_add, lookup_coin_ids = get_hints_and_subscription_coin_ids(
            state_change_summary, self.coin_subscriptions, self.ph_subscriptions
        )
        await self.hint_store.add_hints(hints_to_add)

        sub_slots = await self.blockchain.get_sp_and_ip_sub_slots(record.header_hash)
        assert sub_slots is not None

        if not self.sync_store.get_sync_mode():
            self.blockchain.clean_block_records()

        fork_block: Optional[BlockRecord] = None
        if state_change_summary.fork_height != block.height - 1 and block.height != 0:
            # This is a reorg
            fork_hash: Optional[bytes32] = self.blockchain.height_to_hash(state_change_summary.fork_height)
            assert fork_hash is not None
            fork_block = self.blockchain.block_record(fork_hash)

        fns_peak_result: FullNodeStorePeakResult = self.full_node_store.new_peak(
            record,
            block,
            sub_slots[0],
            sub_slots[1],
            fork_block,
            self.blockchain,
        )

        if fns_peak_result.new_signage_points is not None and peer is not None:
            for index, sp in fns_peak_result.new_signage_points:
                assert (
                    sp.cc_vdf is not None
                    and sp.cc_proof is not None
                    and sp.rc_vdf is not None
                    and sp.rc_proof is not None
                )
                await self.signage_point_post_processing(
                    RespondSignagePoint(index, sp.cc_vdf, sp.cc_proof, sp.rc_vdf, sp.rc_proof), peer, sub_slots[1]
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
        new_npc_results: List[NPCResult] = state_change_summary.new_npc_results
        mempool_new_peak_result: List[Tuple[SpendBundle, NPCResult, bytes32]] = await self.mempool_manager.new_peak(
            self.blockchain.get_peak(), new_npc_results[-1] if len(new_npc_results) > 0 else None
        )

        # Check if we detected a spent transaction, to load up our generator cache
        if block.transactions_generator is not None and self.full_node_store.previous_generator is None:
            generator_arg = detect_potential_template_generator(block.height, block.transactions_generator)
            if generator_arg:
                self.log.info(f"Saving previous generator for height {block.height}")
                self.full_node_store.previous_generator = generator_arg

        return PeakPostProcessingResult(mempool_new_peak_result, fns_peak_result, hints_to_add, lookup_coin_ids)

    async def peak_post_processing_2(
        self,
        block: FullBlock,
        peer: Optional[ws.WSChiaConnection],
        state_change_summary: StateChangeSummary,
        ppp_result: PeakPostProcessingResult,
    ) -> None:
        """
        Does NOT need to be called under the blockchain lock. Handle other parts of post processing like communicating
        with peers
        """
        record = state_change_summary.peak
        for bundle, result, spend_name in ppp_result.mempool_peak_result:
            self.log.debug(f"Added transaction to mempool: {spend_name}")
            mempool_item = self.mempool_manager.get_mempool_item(spend_name)
            assert mempool_item is not None
            fees = mempool_item.fee
            assert fees >= 0
            assert mempool_item.cost is not None
            new_tx = full_node_protocol.NewTransaction(
                spend_name,
                mempool_item.cost,
                fees,
            )
            msg = make_msg(ProtocolMessageTypes.new_transaction, new_tx)
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

        # If there were pending end of slots that happen after this peak, broadcast them if they are added
        if ppp_result.fns_peak_result.added_eos is not None:
            broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                ppp_result.fns_peak_result.added_eos.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                ppp_result.fns_peak_result.added_eos.challenge_chain.get_hash(),
                uint8(0),
                ppp_result.fns_peak_result.added_eos.reward_chain.end_of_slot_vdf.challenge,
            )
            msg = make_msg(ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot, broadcast)
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

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
                    state_change_summary.fork_height,
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
                state_change_summary.fork_height,
            ),
        )
        await self.update_wallets(state_change_summary, ppp_result.hints, ppp_result.lookup_coin_ids)
        await self.server.send_to_all([msg], NodeType.WALLET)
        self._state_changed("new_peak")

    async def respond_block(
        self,
        respond_block: full_node_protocol.RespondBlock,
        peer: Optional[ws.WSChiaConnection] = None,
        raise_on_disconnected: bool = False,
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

        pre_validation_result: Optional[PreValidationResult] = None
        if (
            block.is_transaction_block()
            and block.transactions_info is not None
            and block.transactions_info.generator_root != bytes([0] * 32)
            and block.transactions_generator is None
        ):
            # This is the case where we already had the unfinished block, and asked for this block without
            # the transactions (since we already had them). Therefore, here we add the transactions.
            unfinished_rh: bytes32 = block.reward_chain_block.get_unfinished().get_hash()
            unf_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(unfinished_rh)
            if (
                unf_block is not None
                and unf_block.transactions_generator is not None
                and unf_block.foliage_transaction_block == block.foliage_transaction_block
            ):
                # We checked that the transaction block is the same, therefore all transactions and the signature
                # must be identical in the unfinished and finished blocks. We can therefore use the cache.
                pre_validation_result = self.full_node_store.get_unfinished_block_result(unfinished_rh)
                assert pre_validation_result is not None
                block = dataclasses.replace(
                    block,
                    transactions_generator=unf_block.transactions_generator,
                    transactions_generator_ref_list=unf_block.transactions_generator_ref_list,
                )
            else:
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
        state_change_summary: Optional[StateChangeSummary] = None
        ppp_result: Optional[PeakPostProcessingResult] = None
        async with self._blockchain_lock_high_priority:
            # After acquiring the lock, check again, because another asyncio thread might have added it
            if self.blockchain.contains_block(header_hash):
                return None
            validation_start = time.time()
            # Tries to add the block to the blockchain, if we already validated transactions, don't do it again
            npc_results = {}
            if pre_validation_result is not None and pre_validation_result.npc_result is not None:
                npc_results[block.height] = pre_validation_result.npc_result

            # Don't validate signatures because we want to validate them in the main thread later, since we have a
            # cache available
            pre_validation_results = await self.blockchain.pre_validate_blocks_multiprocessing(
                [block], npc_results, validate_signatures=False
            )
            added: Optional[ReceiveBlockResult] = None
            pre_validation_time = time.time() - validation_start
            try:
                if len(pre_validation_results) < 1:
                    raise ValueError(f"Failed to validate block {header_hash} height {block.height}")
                if pre_validation_results[0].error is not None:
                    if Err(pre_validation_results[0].error) == Err.INVALID_PREV_BLOCK_HASH:
                        added = ReceiveBlockResult.DISCONNECTED_BLOCK
                        error_code: Optional[Err] = Err.INVALID_PREV_BLOCK_HASH
                    else:
                        raise ValueError(
                            f"Failed to validate block {header_hash} height "
                            f"{block.height}: {Err(pre_validation_results[0].error).name}"
                        )
                else:
                    result_to_validate = (
                        pre_validation_results[0] if pre_validation_result is None else pre_validation_result
                    )
                    assert result_to_validate.required_iters == pre_validation_results[0].required_iters
                    (added, error_code, state_change_summary) = await self.blockchain.receive_block(
                        block, result_to_validate, None
                    )
                if added == ReceiveBlockResult.ALREADY_HAVE_BLOCK:
                    return None
                elif added == ReceiveBlockResult.INVALID_BLOCK:
                    assert error_code is not None
                    self.log.error(f"Block {header_hash} at height {block.height} is invalid with code {error_code}.")
                    raise ConsensusError(error_code, [header_hash])
                elif added == ReceiveBlockResult.DISCONNECTED_BLOCK:
                    self.log.info(f"Disconnected block {header_hash} at height {block.height}")
                    if raise_on_disconnected:
                        raise RuntimeError("Expected block to be added, received disconnected block.")
                    return None
                elif added == ReceiveBlockResult.NEW_PEAK:
                    # Only propagate blocks which extend the blockchain (becomes one of the heads)
                    assert state_change_summary is not None
                    ppp_result = await self.peak_post_processing(block, state_change_summary, peer)

                elif added == ReceiveBlockResult.ADDED_AS_ORPHAN:
                    self.log.info(
                        f"Received orphan block of height {block.height} rh " f"{block.reward_chain_block.get_hash()}"
                    )
                else:
                    # Should never reach here, all the cases are covered
                    raise RuntimeError(f"Invalid result from receive_block {added}")
            except asyncio.CancelledError:
                # We need to make sure to always call this method even when we get a cancel exception, to make sure
                # the node stays in sync
                if added == ReceiveBlockResult.NEW_PEAK:
                    assert state_change_summary is not None
                    await self.peak_post_processing(block, state_change_summary, peer)
                raise

            validation_time = time.time() - validation_start

        if ppp_result is not None:
            assert state_change_summary is not None
            await self.peak_post_processing_2(block, peer, state_change_summary, ppp_result)

        percent_full_str = (
            (
                ", percent full: "
                + str(round(100.0 * float(block.transactions_info.cost) / self.constants.MAX_BLOCK_COST_CLVM, 3))
                + "%"
            )
            if block.transactions_info is not None
            else ""
        )
        self.log.log(
            logging.WARNING if validation_time > 2 else logging.DEBUG,
            f"Block validation time: {validation_time:0.2f} seconds, "
            f"pre_validation time: {pre_validation_time:0.2f} seconds, "
            f"cost: {block.transactions_info.cost if block.transactions_info is not None else 'None'}"
            f"{percent_full_str} header_hash: {header_hash} height: {block.height}",
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

        state_changed_data: Dict[str, Any] = {
            "transaction_block": False,
            "k_size": block.reward_chain_block.proof_of_space.size,
            "header_hash": block.header_hash,
            "height": block.height,
            "validation_time": validation_time,
            "pre_validation_time": pre_validation_time,
        }

        if block.transactions_info is not None:
            state_changed_data["transaction_block"] = True
            state_changed_data["block_cost"] = block.transactions_info.cost
            state_changed_data["block_fees"] = block.transactions_info.fees

        if block.foliage_transaction_block is not None:
            state_changed_data["timestamp"] = block.foliage_transaction_block.timestamp

        if block.transactions_generator is not None:
            state_changed_data["transaction_generator_size_bytes"] = len(bytes(block.transactions_generator))

        state_changed_data["transaction_generator_ref_list"] = block.transactions_generator_ref_list
        if added is not None:
            state_changed_data["receive_block_result"] = added.value

        self._state_changed("block", state_changed_data)

        record = self.blockchain.block_record(block.header_hash)
        if self.weight_proof_handler is not None and record.sub_epoch_summary_included is not None:
            if self._segment_task is None or self._segment_task.done():
                self._segment_task = asyncio.create_task(self.weight_proof_handler.create_prev_sub_epoch_segments())
        return None

    async def respond_unfinished_block(
        self,
        respond_unfinished_block: full_node_protocol.RespondUnfinishedBlock,
        peer: Optional[ws.WSChiaConnection],
        farmed_block: bool = False,
        block_bytes: Optional[bytes] = None,
    ) -> None:
        """
        We have received an unfinished block, either created by us, or from another peer.
        We can validate it and if it's a good block, propagate it to other peers and
        timelords.
        """
        block = respond_unfinished_block.unfinished_block
        receive_time = time.time()

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

        # The clvm generator and aggregate signature are validated outside of the lock, to allow other blocks and
        # transactions to get validated
        npc_result: Optional[NPCResult] = None
        pre_validation_time = None

        async with self._blockchain_lock_high_priority:
            start_header_time = time.time()
            _, header_error = await self.blockchain.validate_unfinished_block_header(block)
            if header_error is not None:
                raise ConsensusError(header_error)
            self.log.warning(f"Time for header validate: {time.time() - start_header_time}")

        if block.transactions_generator is not None:
            pre_validation_start = time.time()
            assert block.transactions_info is not None
            try:
                block_generator: Optional[BlockGenerator] = await self.blockchain.get_block_generator(block)
            except ValueError:
                raise ConsensusError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
            if block_generator is None:
                raise ConsensusError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
            if block_bytes is None:
                block_bytes = bytes(block)

            npc_result = await self.blockchain.run_generator(block_bytes, block_generator)
            pre_validation_time = time.time() - pre_validation_start

            # blockchain.run_generator throws on errors, so npc_result is
            # guaranteed to represent a successful run
            assert npc_result.conds is not None
            pairs_pks, pairs_msgs = pkm_pairs(npc_result.conds, self.constants.AGG_SIG_ME_ADDITIONAL_DATA)
            if not cached_bls.aggregate_verify(
                pairs_pks, pairs_msgs, block.transactions_info.aggregated_signature, True
            ):
                raise ConsensusError(Err.BAD_AGGREGATE_SIGNATURE)

        async with self._blockchain_lock_high_priority:
            # TODO: pre-validate VDFs outside of lock
            validation_start = time.time()
            validate_result = await self.blockchain.validate_unfinished_block(block, npc_result)
            if validate_result.error is not None:
                if validate_result.error == Err.COIN_AMOUNT_NEGATIVE.value:
                    # TODO: remove in the future, hotfix for 1.1.5 peers to not disconnect older peers
                    self.log.info(f"Consensus error {validate_result.error}, not disconnecting")
                    return
                raise ConsensusError(Err(validate_result.error))
            validation_time = time.time() - validation_start

        # respond_block will later use the cache (validated_signature=True)
        validate_result = dataclasses.replace(validate_result, validated_signature=True)

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
        pre_validation_log = (
            f"pre_validation time {pre_validation_time:0.4f}, " if pre_validation_time is not None else ""
        )
        if farmed_block is True:
            self.log.info(
                f"🍀 ️Farmed unfinished_block {block_hash}, SP: {block.reward_chain_block.signage_point_index}, "
                f"validation time: {validation_time:0.4f} seconds, {pre_validation_log}"
                f"cost: {block.transactions_info.cost if block.transactions_info else 'None'} "
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
                f"{receive_time - self.signage_point_times[block.reward_chain_block.signage_point_index]:0.4f}, "
                f"Pool pk {encode_puzzle_hash(block.foliage.foliage_block_data.pool_target.puzzle_hash, 'xch')}, "
                f"validation time: {validation_time:0.4f} seconds, {pre_validation_log}"
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
        self, request: timelord_protocol.NewInfusionPointVDF, timelord_peer: Optional[ws.WSChiaConnection] = None
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
            await self.respond_block(full_node_protocol.RespondBlock(block), raise_on_disconnected=True)
        except Exception as e:
            self.log.warning(f"Consensus error validating block: {e}")
            if timelord_peer is not None:
                # Only sends to the timelord who sent us this VDF, to reset them to the correct peak
                await self.send_peak_to_timelords(peer=timelord_peer)
        return None

    async def respond_end_of_sub_slot(
        self, request: full_node_protocol.RespondEndOfSubSlot, peer: ws.WSChiaConnection
    ) -> Tuple[Optional[Message], bool]:

        fetched_ss = self.full_node_store.get_sub_slot(request.end_of_slot_bundle.challenge_chain.get_hash())

        # We are not interested in sub-slots which have the same challenge chain but different reward chain. If there
        # is a reorg, we will find out through the broadcast of blocks instead.
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
                    bytes32([0] * 32),
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
        peer: Optional[ws.WSChiaConnection] = None,
        test: bool = False,
        tx_bytes: Optional[bytes] = None,
    ) -> Tuple[MempoolInclusionStatus, Optional[Err]]:
        if self.sync_store.get_sync_mode():
            return MempoolInclusionStatus.FAILED, Err.NO_TRANSACTIONS_WHILE_SYNCING
        if not test and not (await self.synced()):
            return MempoolInclusionStatus.FAILED, Err.NO_TRANSACTIONS_WHILE_SYNCING

        if self.mempool_manager.get_spendbundle(spend_name) is not None:
            self.mempool_manager.remove_seen(spend_name)
            return MempoolInclusionStatus.SUCCESS, None
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
                cost_result = await self.mempool_manager.pre_validate_spendbundle(transaction, tx_bytes, spend_name)
            except ValidationError as e:
                self.mempool_manager.remove_seen(spend_name)
                return MempoolInclusionStatus.FAILED, e.code
            except Exception:
                self.mempool_manager.remove_seen(spend_name)
                raise
            async with self._blockchain_lock_low_priority:
                if self.mempool_manager.get_spendbundle(spend_name) is not None:
                    self.mempool_manager.remove_seen(spend_name)
                    return MempoolInclusionStatus.SUCCESS, None
                cost, status, error = await self.mempool_manager.add_spend_bundle(transaction, cost_result, spend_name)
            if status == MempoolInclusionStatus.SUCCESS:
                self.log.debug(
                    f"Added transaction to mempool: {spend_name} mempool size: "
                    f"{self.mempool_manager.mempool.total_mempool_cost} normalized "
                    f"{self.mempool_manager.mempool.total_mempool_cost / 5000000}"
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
                if self.simulator_transaction_callback is not None:  # callback
                    await self.simulator_transaction_callback(spend_name)  # pylint: disable=E1102
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
        peak = self.blockchain.get_peak()
        if peak is None or peak.height - height < 5:
            self.log.debug("Will not compactify recent block")
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

    # returns True if we ended up replacing the proof, and False otherwise
    async def _replace_proof(
        self,
        vdf_info: VDFInfo,
        vdf_proof: VDFProof,
        header_hash: bytes32,
        field_vdf: CompressibleVDFField,
    ) -> bool:

        block = await self.block_store.get_full_block(header_hash)
        if block is None:
            return False

        new_block = None

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
            return False
        async with self.db_wrapper.writer():
            try:
                await self.block_store.replace_proof(header_hash, new_block)
                return True
            except BaseException as e:
                self.log.error(
                    f"_replace_proof error while adding block {block.header_hash} height {block.height},"
                    f" rolling back: {e} {traceback.format_exc()}"
                )
                raise

    async def respond_compact_proof_of_time(self, request: timelord_protocol.RespondCompactProofOfTime) -> None:
        field_vdf = CompressibleVDFField(int(request.field_vdf))
        if not await self._can_accept_compact_proof(
            request.vdf_info, request.vdf_proof, request.height, request.header_hash, field_vdf
        ):
            return None
        async with self.blockchain.compact_proof_lock:
            replaced = await self._replace_proof(request.vdf_info, request.vdf_proof, request.header_hash, field_vdf)
        if not replaced:
            self.log.error(f"Could not replace compact proof: {request.height}")
            return None
        self.log.info(f"Replaced compact proof at height {request.height}")
        msg = make_msg(
            ProtocolMessageTypes.new_compact_vdf,
            full_node_protocol.NewCompactVDF(request.height, request.header_hash, request.field_vdf, request.vdf_info),
        )
        if self._server is not None:
            await self.server.send_to_all([msg], NodeType.FULL_NODE)

    async def new_compact_vdf(self, request: full_node_protocol.NewCompactVDF, peer: ws.WSChiaConnection) -> None:
        is_fully_compactified = await self.block_store.is_fully_compactified(request.header_hash)
        if is_fully_compactified is None or is_fully_compactified:
            return None
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

    async def request_compact_vdf(
        self, request: full_node_protocol.RequestCompactVDF, peer: ws.WSChiaConnection
    ) -> None:
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

    async def respond_compact_vdf(
        self, request: full_node_protocol.RespondCompactVDF, peer: ws.WSChiaConnection
    ) -> None:
        field_vdf = CompressibleVDFField(int(request.field_vdf))
        if not await self._can_accept_compact_proof(
            request.vdf_info, request.vdf_proof, request.height, request.header_hash, field_vdf
        ):
            return None
        async with self.blockchain.compact_proof_lock:
            if self.blockchain.seen_compact_proofs(request.vdf_info, request.height):
                return None
            replaced = await self._replace_proof(request.vdf_info, request.vdf_proof, request.header_hash, field_vdf)
        if not replaced:
            self.log.error(f"Could not replace compact proof: {request.height}")
            return None
        msg = make_msg(
            ProtocolMessageTypes.new_compact_vdf,
            full_node_protocol.NewCompactVDF(request.height, request.header_hash, request.field_vdf, request.vdf_info),
        )
        if self._server is not None:
            await self.server.send_to_all_except([msg], NodeType.FULL_NODE, peer.peer_node_id)

    async def broadcast_uncompact_blocks(
        self, uncompact_interval_scan: int, target_uncompact_proofs: int, sanitize_weight_proof_only: bool
    ) -> None:
        try:
            while not self._shut_down:
                while self.sync_store.get_sync_mode() or self.sync_store.get_long_sync():
                    if self._shut_down:
                        return None
                    await asyncio.sleep(30)

                broadcast_list: List[timelord_protocol.RequestCompactProofOfTime] = []

                self.log.info("Getting random heights for bluebox to compact")
                heights = await self.block_store.get_random_not_compactified(target_uncompact_proofs)
                self.log.info("Heights found for bluebox to compact: [%s]" % ", ".join(map(str, heights)))

                for h in heights:

                    headers = await self.blockchain.get_header_blocks_in_range(h, h, tx_filter=False)
                    records: Dict[bytes32, BlockRecord] = {}
                    if sanitize_weight_proof_only:
                        records = await self.blockchain.get_block_records_in_range(h, h)
                    for header in headers.values():
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

                if len(broadcast_list) > target_uncompact_proofs:
                    broadcast_list = broadcast_list[:target_uncompact_proofs]
                if self.sync_store.get_sync_mode() or self.sync_store.get_long_sync():
                    continue
                if self._server is not None:
                    self.log.info(f"Broadcasting {len(broadcast_list)} items to the bluebox")
                    msgs = []
                    for new_pot in broadcast_list:
                        msg = make_msg(ProtocolMessageTypes.request_compact_proof_of_time, new_pot)
                        msgs.append(msg)
                    await self.server.send_to_all(msgs, NodeType.TIMELORD)
                await asyncio.sleep(uncompact_interval_scan)
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception in broadcast_uncompact_blocks: {e}")
            self.log.error(f"Exception Stack: {error_stack}")


async def node_next_block_check(
    peer: ws.WSChiaConnection, potential_peek: uint32, blockchain: BlockchainInterface
) -> bool:

    block_response: Optional[Any] = await peer.request_block(full_node_protocol.RequestBlock(potential_peek, True))
    if block_response is not None and isinstance(block_response, full_node_protocol.RespondBlock):
        peak = blockchain.get_peak()
        if peak is not None and block_response.block.prev_header_hash == peak.header_hash:
            return True
    return False
