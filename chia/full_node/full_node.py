from __future__ import annotations

import asyncio
import contextlib
import copy
import dataclasses
import logging
import multiprocessing
import random
import sqlite3
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Sequence
from multiprocessing.context import BaseContext
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Optional, TextIO, Union, cast, final

from chia_rs import (
    AugSchemeMPL,
    BlockRecord,
    BLSCache,
    CoinState,
    ConsensusConstants,
    EndOfSubSlotBundle,
    FullBlock,
    HeaderBlock,
    PoolTarget,
    SpendBundle,
    SubEpochSummary,
    UnfinishedBlock,
    get_flags_for_height_and_constants,
    run_block_generator,
    run_block_generator2,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64, uint128
from packaging.version import Version

from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.block_creation import unfinished_block_to_full_block
from chia.consensus.blockchain import AddBlockResult, Blockchain, BlockchainMutexPriority, StateChangeSummary
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.coin_store_protocol import CoinStoreProtocol
from chia.consensus.condition_tools import pkm_pairs
from chia.consensus.cost_calculator import NPCResult
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.consensus.multiprocess_validation import PreValidationResult, pre_validate_block
from chia.consensus.pot_iterations import calculate_sp_iters
from chia.consensus.signage_point import SignagePoint
from chia.full_node.block_height_map import BlockHeightMap
from chia.full_node.block_store import BlockStore
from chia.full_node.check_fork_next_block import check_fork_next_block
from chia.full_node.coin_store import CoinStore
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.full_node_store import FullNodeStore, FullNodeStorePeakResult, UnfinishedBlockEntry
from chia.full_node.hint_management import get_hints_and_subscription_coin_ids
from chia.full_node.hint_store import HintStore
from chia.full_node.mempool import MempoolRemoveInfo
from chia.full_node.mempool_manager import MempoolManager, NewPeakItem
from chia.full_node.subscriptions import PeerSubscriptions, peers_for_spend_bundle
from chia.full_node.sync_store import Peak, SyncStore
from chia.full_node.tx_processing_queue import TransactionQueue, TransactionQueueEntry
from chia.full_node.weight_proof import WeightProofHandler
from chia.protocols import farmer_protocol, full_node_protocol, timelord_protocol, wallet_protocol
from chia.protocols.farmer_protocol import SignagePointSourceData, SPSubSlotSourceData, SPVDFSourceData
from chia.protocols.full_node_protocol import RequestBlocks, RespondBlock, RespondBlocks, RespondSignagePoint
from chia.protocols.outbound_message import Message, NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.protocols.wallet_protocol import CoinStateUpdate, RemovedMempoolItem
from chia.rpc.rpc_server import StateChangedProtocol
from chia.server.node_discovery import FullNodePeers
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.vdf import CompressibleVDFField, VDFInfo, VDFProof, validate_vdf
from chia.types.coin_record import CoinRecord
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import MempoolItem
from chia.types.peer_info import PeerInfo
from chia.types.validation_state import ValidationState
from chia.types.weight_proof import WeightProof
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import process_config_start_method
from chia.util.db_synchronous import db_synchronous_on
from chia.util.db_version import lookup_db_version, set_db_version_async
from chia.util.db_wrapper import DBWrapper2, manage_connection
from chia.util.errors import ConsensusError, Err, TimestampError, ValidationError
from chia.util.limited_semaphore import LimitedSemaphore
from chia.util.network import is_localhost
from chia.util.path import path_from_root
from chia.util.profiler import enable_profiler, mem_profile_task, profile_task
from chia.util.safe_cancel_task import cancel_task_safe
from chia.util.task_referencer import create_referenced_task


# This is the result of calling peak_post_processing, which is then fed into peak_post_processing_2
@dataclasses.dataclass
class PeakPostProcessingResult:
    mempool_peak_result: list[NewPeakItem]  # The new items from calling MempoolManager.new_peak
    mempool_removals: list[MempoolRemoveInfo]  # The removed mempool items from calling MempoolManager.new_peak
    fns_peak_result: FullNodeStorePeakResult  # The result of calling FullNodeStore.new_peak
    hints: list[tuple[bytes32, bytes]]  # The hints added to the DB
    lookup_coin_ids: list[bytes32]  # The coin IDs that we need to look up to notify wallets of changes
    signage_points: list[tuple[RespondSignagePoint, WSChiaConnection, Optional[EndOfSubSlotBundle]]]


@dataclasses.dataclass(frozen=True)
class WalletUpdate:
    fork_height: uint32
    peak: Peak
    coin_records: list[CoinRecord]
    hints: dict[bytes32, bytes32]


@final
@dataclasses.dataclass
class FullNode:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcServiceProtocol

        _protocol_check: ClassVar[RpcServiceProtocol] = cast("FullNode", None)

    root_path: Path
    config: dict[str, Any]
    constants: ConsensusConstants
    signage_point_times: list[float]
    full_node_store: FullNodeStore
    log: logging.Logger
    db_path: Path
    wallet_sync_queue: asyncio.Queue[WalletUpdate]
    _segment_task_list: list[asyncio.Task[None]] = dataclasses.field(default_factory=list)
    initialized: bool = False
    _server: Optional[ChiaServer] = None
    _shut_down: bool = False
    pow_creation: dict[bytes32, asyncio.Event] = dataclasses.field(default_factory=dict)
    state_changed_callback: Optional[StateChangedProtocol] = None
    full_node_peers: Optional[FullNodePeers] = None
    sync_store: SyncStore = dataclasses.field(default_factory=SyncStore)
    uncompact_task: Optional[asyncio.Task[None]] = None
    compact_vdf_requests: set[bytes32] = dataclasses.field(default_factory=set)
    # TODO: Logging isn't setup yet so the log entries related to parsing the
    #       config would end up on stdout if handled here.
    multiprocessing_context: Optional[BaseContext] = None
    _ui_tasks: set[asyncio.Task[None]] = dataclasses.field(default_factory=set)
    subscriptions: PeerSubscriptions = dataclasses.field(default_factory=PeerSubscriptions)
    _transaction_queue_task: Optional[asyncio.Task[None]] = None
    simulator_transaction_callback: Optional[Callable[[bytes32], Awaitable[None]]] = None
    _sync_task_list: list[asyncio.Task[None]] = dataclasses.field(default_factory=list)
    _transaction_queue: Optional[TransactionQueue] = None
    _tx_task_list: list[asyncio.Task[None]] = dataclasses.field(default_factory=list)
    _compact_vdf_sem: Optional[LimitedSemaphore] = None
    _new_peak_sem: Optional[LimitedSemaphore] = None
    _add_transaction_semaphore: Optional[asyncio.Semaphore] = None
    _db_wrapper: Optional[DBWrapper2] = None
    _hint_store: Optional[HintStore] = None
    _block_store: Optional[BlockStore] = None
    _coin_store: Optional[CoinStoreProtocol] = None
    _mempool_manager: Optional[MempoolManager] = None
    _init_weight_proof: Optional[asyncio.Task[None]] = None
    _blockchain: Optional[Blockchain] = None
    _timelord_lock: Optional[asyncio.Lock] = None
    weight_proof_handler: Optional[WeightProofHandler] = None
    # hashes of peaks that failed long sync on chip13 Validation
    bad_peak_cache: dict[bytes32, uint32] = dataclasses.field(default_factory=dict)
    wallet_sync_task: Optional[asyncio.Task[None]] = None
    _bls_cache: BLSCache = dataclasses.field(default_factory=lambda: BLSCache(50000))

    @property
    def server(self) -> ChiaServer:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    @classmethod
    async def create(
        cls,
        config: dict[str, Any],
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = __name__,
    ) -> FullNode:
        # NOTE: async to force the queue creation to occur when an event loop is available
        db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
        db_path = path_from_root(root_path, db_path_replaced)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            root_path=root_path,
            config=config,
            constants=consensus_constants,
            signage_point_times=[time.time() for _ in range(consensus_constants.NUM_SPS_SUB_SLOT)],
            full_node_store=FullNodeStore(consensus_constants),
            log=logging.getLogger(name),
            db_path=db_path,
            wallet_sync_queue=asyncio.Queue(),
        )

    @contextlib.asynccontextmanager
    async def manage(self) -> AsyncIterator[None]:
        self._timelord_lock = asyncio.Lock()
        self._compact_vdf_sem = LimitedSemaphore.create(active_limit=4, waiting_limit=20)

        # We don't want to run too many concurrent new_peak instances, because it would fetch the same block from
        # multiple peers and re-validate.
        self._new_peak_sem = LimitedSemaphore.create(active_limit=2, waiting_limit=20)

        # These many respond_transaction tasks can be active at any point in time
        self._add_transaction_semaphore = asyncio.Semaphore(200)

        sql_log_path: Optional[Path] = None
        with contextlib.ExitStack() as exit_stack:
            sql_log_file: Optional[TextIO] = None
            if self.config.get("log_sqlite_cmds", False):
                sql_log_path = path_from_root(self.root_path, "log/sql.log")
                self.log.info(f"logging SQL commands to {sql_log_path}")
                sql_log_file = exit_stack.enter_context(sql_log_path.open("a", encoding="utf-8"))

            # create the store (db) and full node instance
            # TODO: is this standardized and thus able to be handled by DBWrapper2?
            async with manage_connection(self.db_path, log_file=sql_log_file, name="version_check") as db_connection:
                db_version = await lookup_db_version(db_connection)

        self.log.info(f"using blockchain database {self.db_path}, which is version {db_version}")

        db_sync = db_synchronous_on(self.config.get("db_sync", "auto"))
        self.log.info(f"opening blockchain DB: synchronous={db_sync}")

        async with DBWrapper2.managed(
            self.db_path,
            db_version=db_version,
            reader_count=self.config.get("db_readers", 4),
            log_path=sql_log_path,
            synchronous=db_sync,
        ) as self._db_wrapper:
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
            self._hint_store = await HintStore.create(self.db_wrapper)
            self._coin_store = await CoinStore.create(self.db_wrapper)
            self.log.info("Initializing blockchain from disk")
            start_time = time.monotonic()
            reserved_cores = self.config.get("reserved_cores", 0)
            single_threaded = self.config.get("single_threaded", False)
            log_coins = self.config.get("log_coins", False)
            multiprocessing_start_method = process_config_start_method(config=self.config, log=self.log)
            self.multiprocessing_context = multiprocessing.get_context(method=multiprocessing_start_method)
            selected_network = self.config.get("selected_network")
            height_map = await BlockHeightMap.create(self.db_path.parent, self._db_wrapper, selected_network)
            self._blockchain = await Blockchain.create(
                coin_store=self.coin_store,
                block_store=self.block_store,
                consensus_constants=self.constants,
                height_map=height_map,
                reserved_cores=reserved_cores,
                single_threaded=single_threaded,
                log_coins=log_coins,
            )

            self._mempool_manager = MempoolManager(
                get_coin_records=self.coin_store.get_coin_records,
                get_unspent_lineage_info_for_puzzle_hash=self.coin_store.get_unspent_lineage_info_for_puzzle_hash,
                consensus_constants=self.constants,
                single_threaded=single_threaded,
            )

            # Transactions go into this queue from the server, and get sent to respond_transaction
            self._transaction_queue = TransactionQueue(1000, self.log)
            self._transaction_queue_task: asyncio.Task[None] = create_referenced_task(self._handle_transactions())

            self._init_weight_proof = create_referenced_task(self.initialize_weight_proof())

            if self.config.get("enable_profiler", False):
                create_referenced_task(profile_task(self.root_path, "node", self.log), known_unreferenced=True)

            self.profile_block_validation = self.config.get("profile_block_validation", False)
            if self.profile_block_validation:  # pragma: no cover
                # this is not covered by any unit tests as it's essentially test code
                # itself. It's exercised manually when investigating performance issues
                profile_dir = path_from_root(self.root_path, "block-validation-profile")
                profile_dir.mkdir(parents=True, exist_ok=True)

            if self.config.get("enable_memory_profiler", False):
                create_referenced_task(mem_profile_task(self.root_path, "node", self.log), known_unreferenced=True)

            time_taken = time.monotonic() - start_time
            peak: Optional[BlockRecord] = self.blockchain.get_peak()
            if peak is None:
                self.log.info(f"Initialized with empty blockchain time taken: {int(time_taken)}s")
                if not await self.coin_store.is_empty():
                    self.log.error(
                        "Inconsistent blockchain DB file! Could not find peak block but found some coins! "
                        "This is a fatal error. The blockchain database may be corrupt"
                    )
                    raise RuntimeError("corrupt blockchain DB")
            else:
                self.log.info(
                    f"Blockchain initialized to peak {peak.header_hash} height"
                    f" {peak.height}, "
                    f"time taken: {int(time_taken)}s"
                )
                async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
                    pending_tx = await self.mempool_manager.new_peak(self.blockchain.get_tx_peak(), None)
                    assert len(pending_tx.items) == 0  # no pending transactions when starting up

                    full_peak: Optional[FullBlock] = await self.blockchain.get_full_peak()
                    assert full_peak is not None
                    state_change_summary = StateChangeSummary(peak, uint32(max(peak.height - 1, 0)), [], [], [], [])
                    # Must be called under priority_mutex
                    ppp_result: PeakPostProcessingResult = await self.peak_post_processing(
                        full_peak, state_change_summary, None
                    )
                # Can be called outside of priority_mutex
                await self.peak_post_processing_2(full_peak, None, state_change_summary, ppp_result)
            if self.config["send_uncompact_interval"] != 0:
                sanitize_weight_proof_only = False
                if "sanitize_weight_proof_only" in self.config:
                    sanitize_weight_proof_only = self.config["sanitize_weight_proof_only"]
                assert self.config["target_uncompact_proofs"] != 0
                self.uncompact_task = create_referenced_task(
                    self.broadcast_uncompact_blocks(
                        self.config["send_uncompact_interval"],
                        self.config["target_uncompact_proofs"],
                        sanitize_weight_proof_only,
                    )
                )
            if self.wallet_sync_task is None or self.wallet_sync_task.done():
                self.wallet_sync_task = create_referenced_task(self._wallets_sync_task_handler())

            self.initialized = True

            try:
                async with contextlib.AsyncExitStack() as aexit_stack:
                    if self.full_node_peers is not None:
                        await aexit_stack.enter_async_context(self.full_node_peers.manage())
                    yield
            finally:
                self._shut_down = True
                if self._init_weight_proof is not None:
                    self._init_weight_proof.cancel()

                # blockchain is created in _start and in certain cases it may not exist here during _close
                if self._blockchain is not None:
                    self.blockchain.shut_down()
                # same for mempool_manager
                if self._mempool_manager is not None:
                    self.mempool_manager.shut_down()
                if self.uncompact_task is not None:
                    self.uncompact_task.cancel()
                if self._transaction_queue_task is not None:
                    self._transaction_queue_task.cancel()
                cancel_task_safe(task=self.wallet_sync_task, log=self.log)
                for one_tx_task in self._tx_task_list:
                    if not one_tx_task.done():
                        cancel_task_safe(task=one_tx_task, log=self.log)
                for one_sync_task in self._sync_task_list:
                    if not one_sync_task.done():
                        cancel_task_safe(task=one_sync_task, log=self.log)
                for segment_task in self._segment_task_list:
                    cancel_task_safe(segment_task, self.log)
                for task_id, task in list(self.full_node_store.tx_fetch_tasks.items()):
                    cancel_task_safe(task, self.log)
                if self._init_weight_proof is not None:
                    await asyncio.wait([self._init_weight_proof])
                for one_tx_task in self._tx_task_list:
                    if one_tx_task.done():
                        self.log.info(f"TX task {one_tx_task.get_name()} done")
                    else:
                        with contextlib.suppress(asyncio.CancelledError):
                            self.log.info(f"Awaiting TX task {one_tx_task.get_name()}")
                            await one_tx_task
                for one_sync_task in self._sync_task_list:
                    if one_sync_task.done():
                        self.log.info(f"Long sync task {one_sync_task.get_name()} done")
                    else:
                        with contextlib.suppress(asyncio.CancelledError):
                            self.log.info(f"Awaiting long sync task {one_sync_task.get_name()}")
                            await one_sync_task
                await asyncio.gather(*self._segment_task_list, return_exceptions=True)

    @property
    def block_store(self) -> BlockStore:
        assert self._block_store is not None
        return self._block_store

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
    def coin_store(self) -> CoinStoreProtocol:
        assert self._coin_store is not None
        return self._coin_store

    @property
    def add_transaction_semaphore(self) -> asyncio.Semaphore:
        assert self._add_transaction_semaphore is not None
        return self._add_transaction_semaphore

    @property
    def transaction_queue(self) -> TransactionQueue:
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
    def new_peak_sem(self) -> LimitedSemaphore:
        assert self._new_peak_sem is not None
        return self._new_peak_sem

    @property
    def compact_vdf_sem(self) -> LimitedSemaphore:
        assert self._compact_vdf_sem is not None
        return self._compact_vdf_sem

    def get_connections(self, request_node_type: Optional[NodeType]) -> list[dict[str, Any]]:
        connections = self.server.get_connections(request_node_type)
        con_info: list[dict[str, Any]] = []
        if self.sync_store is not None:
            peak_store = self.sync_store.peer_to_peak
        else:
            peak_store = None
        for con in connections:
            if peak_store is not None and con.peer_node_id in peak_store:
                peak = peak_store[con.peer_node_id]
                peak_height = peak.height
                peak_hash = peak.header_hash
                peak_weight = peak.weight
            else:
                peak_height = None
                peak_hash = None
                peak_weight = None
            con_dict: dict[str, Any] = {
                "type": con.connection_type,
                "local_port": con.local_port,
                "peer_host": con.peer_info.host,
                "peer_port": con.peer_info.port,
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

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        self.state_changed_callback = callback

    async def _handle_one_transaction(self, entry: TransactionQueueEntry) -> None:
        peer = entry.peer
        try:
            inc_status, err = await self.add_transaction(entry.transaction, entry.spend_name, peer, entry.test)
            entry.done.set((inc_status, err))
        except asyncio.CancelledError:
            error_stack = traceback.format_exc()
            self.log.debug(f"Cancelling _handle_one_transaction, closing: {error_stack}")
        except Exception:
            error_stack = traceback.format_exc()
            self.log.error(f"Error in _handle_one_transaction, closing: {error_stack}")
            if peer is not None:
                await peer.close()
        finally:
            self.add_transaction_semaphore.release()

    async def _handle_transactions(self) -> None:
        while not self._shut_down:
            # We use a semaphore to make sure we don't send more than 200 concurrent calls of respond_transaction.
            # However, doing them one at a time would be slow, because they get sent to other processes.
            await self.add_transaction_semaphore.acquire()

            # Clean up task reference list (used to prevent gc from killing running tasks)
            for oldtask in self._tx_task_list[:]:
                if oldtask.done():
                    self._tx_task_list.remove(oldtask)

            item: TransactionQueueEntry = await self.transaction_queue.pop()
            self._tx_task_list.append(create_referenced_task(self._handle_one_transaction(item)))

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
        dns_servers: list[str] = []
        network_name = self.config["selected_network"]
        try:
            default_port = self.config["network_overrides"]["config"][network_name]["default_full_node_port"]
        except Exception:
            self.log.info("Default port field not found in config.")
            default_port = None
        if "dns_servers" in self.config:
            dns_servers = self.config["dns_servers"]
        elif network_name == "mainnet":
            # If `dns_servers` is missing from the `config`, hardcode it if we're running mainnet.
            dns_servers.append("dns-introducer.chia.net")
        try:
            self.full_node_peers = FullNodePeers(
                server=self.server,
                target_outbound_count=self.config["target_outbound_peer_count"],
                peers_file_path=self.root_path / Path(self.config.get("peers_file_path", "db/peers.dat")),
                introducer_info=self.config["introducer_peer"],
                dns_servers=dns_servers,
                peer_connect_interval=self.config["peer_connect_interval"],
                selected_network=self.config["selected_network"],
                default_port=default_port,
                log=self.log,
            )
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception: {e}")
            self.log.error(f"Exception in peer discovery: {e}")
            self.log.error(f"Exception Stack: {error_stack}")

    def _state_changed(self, change: str, change_data: Optional[dict[str, Any]] = None) -> None:
        if self.state_changed_callback is not None:
            self.state_changed_callback(change, change_data)

    async def short_sync_batch(self, peer: WSChiaConnection, start_height: uint32, target_height: uint32) -> bool:
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

        if self.sync_store.is_backtrack_syncing(node_id=peer.peer_node_id):
            return True  # Don't batch sync, we are already in progress of a backtrack sync
        if peer.peer_node_id in self.sync_store.batch_syncing:
            return True  # Don't trigger a long sync
        self.sync_store.batch_syncing.add(peer.peer_node_id)

        self.log.info(f"Starting batch short sync from {start_height} to height {target_height}")
        if start_height > 0:
            first = await peer.call_api(
                FullNodeAPI.request_block, full_node_protocol.RequestBlock(uint32(start_height), False)
            )
            if first is None or not isinstance(first, full_node_protocol.RespondBlock):
                self.sync_store.batch_syncing.remove(peer.peer_node_id)
                self.log.error(f"Error short batch syncing, could not fetch block at height {start_height}")
                return False
            hash = self.blockchain.height_to_hash(first.block.height - 1)
            assert hash is not None
            if hash != first.block.prev_header_hash:
                self.log.info("Batch syncing stopped, this is a deep chain")
                self.sync_store.batch_syncing.remove(peer.peer_node_id)
                # First sb not connected to our blockchain, do a long sync instead
                return False

        batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
        for task in self._segment_task_list[:]:
            if task.done():
                self._segment_task_list.remove(task)
            else:
                cancel_task_safe(task=task, log=self.log)

        try:
            peer_info = peer.get_peer_logging()
            if start_height > 0:
                fork_hash = self.blockchain.height_to_hash(uint32(start_height - 1))
            else:
                fork_hash = self.constants.GENESIS_CHALLENGE
            assert fork_hash
            fork_info = ForkInfo(start_height - 1, start_height - 1, fork_hash)
            blockchain = AugmentedBlockchain(self.blockchain)
            for height in range(start_height, target_height, batch_size):
                end_height = min(target_height, height + batch_size)
                request = RequestBlocks(uint32(height), uint32(end_height), True)
                response = await peer.call_api(FullNodeAPI.request_blocks, request)
                if not response:
                    raise ValueError(f"Error short batch syncing, invalid/no response for {height}-{end_height}")
                async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
                    state_change_summary: Optional[StateChangeSummary]
                    prev_b = None
                    if response.blocks[0].height > 0:
                        prev_b = await self.blockchain.get_block_record_from_db(response.blocks[0].prev_header_hash)
                        assert prev_b is not None
                    new_slot = len(response.blocks[0].finished_sub_slots) > 0
                    ssi, diff = get_next_sub_slot_iters_and_difficulty(
                        self.constants, new_slot, prev_b, self.blockchain
                    )
                    vs = ValidationState(ssi, diff, None)
                    success, state_change_summary = await self.add_block_batch(
                        response.blocks, peer_info, fork_info, vs, blockchain
                    )
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
                        except Exception:
                            # Still do post processing after cancel (or exception)
                            peak_fb = await self.blockchain.get_full_peak()
                            assert peak_fb is not None
                            await self.peak_post_processing(peak_fb, state_change_summary, peer)
                            raise
                        finally:
                            self.log.info(f"Added blocks {height}-{end_height}")
                if state_change_summary is not None and peak_fb is not None:
                    # Call outside of priority_mutex to encourage concurrency
                    await self.peak_post_processing_2(peak_fb, peer, state_change_summary, ppp_result)
        finally:
            self.sync_store.batch_syncing.remove(peer.peer_node_id)
        return True

    async def short_sync_backtrack(
        self, peer: WSChiaConnection, peak_height: uint32, target_height: uint32, target_unf_hash: bytes32
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
            self.sync_store.increment_backtrack_syncing(node_id=peer.peer_node_id)

            unfinished_block: Optional[UnfinishedBlock] = self.full_node_store.get_unfinished_block(target_unf_hash)
            curr_height: int = target_height
            found_fork_point = False
            blocks = []
            while curr_height > peak_height - 5:
                # If we already have the unfinished block, don't fetch the transactions. In the normal case, we will
                # already have the unfinished block, from when it was broadcast, so we just need to download the header,
                # but not the transactions
                fetch_tx: bool = unfinished_block is None or curr_height != target_height
                curr = await peer.call_api(
                    FullNodeAPI.request_block, full_node_protocol.RequestBlock(uint32(curr_height), fetch_tx)
                )
                if curr is None:
                    raise ValueError(f"Failed to fetch block {curr_height} from {peer.get_peer_logging()}, timed out")
                if curr is None or not isinstance(curr, full_node_protocol.RespondBlock):
                    raise ValueError(
                        f"Failed to fetch block {curr_height} from {peer.get_peer_logging()}, wrong type {type(curr)}"
                    )
                blocks.append(curr.block)
                if curr_height == 0:
                    found_fork_point = True
                    break
                hash_at_height = self.blockchain.height_to_hash(curr.block.height - 1)
                if hash_at_height is not None and hash_at_height == curr.block.prev_header_hash:
                    found_fork_point = True
                    break
                curr_height -= 1
            if found_fork_point:
                first_block = blocks[-1]  # blocks are reveresd this is the lowest block to add
                # we create the fork_info and pass it here so it would be updated on each call to add_block
                fork_info = ForkInfo(first_block.height - 1, first_block.height - 1, first_block.prev_header_hash)
                for block in reversed(blocks):
                    # when syncing, we won't share any signatures with the
                    # mempool, so there's no need to pass in the BLS cache.
                    await self.add_block(block, peer, fork_info=fork_info)
        except (asyncio.CancelledError, Exception):
            self.sync_store.decrement_backtrack_syncing(node_id=peer.peer_node_id)
            raise

        self.sync_store.decrement_backtrack_syncing(node_id=peer.peer_node_id)
        return found_fork_point

    async def _refresh_ui_connections(self, sleep_before: float = 0) -> None:
        if sleep_before > 0:
            await asyncio.sleep(sleep_before)
        self._state_changed("peer_changed_peak")

    async def new_peak(self, request: full_node_protocol.NewPeak, peer: WSChiaConnection) -> None:
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
                self._ui_tasks.add(create_referenced_task(self._refresh_ui_connections(1.5)))
            # Prune completed connect tasks
            self._ui_tasks = set(filter(lambda t: not t.done(), self._ui_tasks))
        except Exception as e:
            self.log.warning(f"Exception UI refresh task: {e}")

        # Store this peak/peer combination in case we want to sync to it, and to keep track of peers
        self.sync_store.peer_has_block(request.header_hash, peer.peer_node_id, request.weight, request.height, True)

        if self.blockchain.contains_block(request.header_hash, request.height):
            return None

        # Not interested in less heavy peaks
        peak: Optional[BlockRecord] = self.blockchain.get_peak()
        curr_peak_height = uint32(0) if peak is None else peak.height
        if peak is not None and peak.weight > request.weight:
            return None

        if self.sync_store.get_sync_mode():
            # If peer connects while we are syncing, check if they have the block we are syncing towards
            target_peak = self.sync_store.target_peak
            if target_peak is not None and request.header_hash != target_peak.header_hash:
                peak_peers: set[bytes32] = self.sync_store.get_peers_that_have_peak([target_peak.header_hash])
                # Don't ask if we already know this peer has the peak
                if peer.peer_node_id not in peak_peers:
                    target_peak_response: Optional[RespondBlock] = await peer.call_api(
                        FullNodeAPI.request_block,
                        full_node_protocol.RequestBlock(target_peak.height, False),
                        timeout=10,
                    )
                    if (
                        target_peak_response is not None
                        and isinstance(target_peak_response, RespondBlock)
                        and target_peak_response.block.header_hash == target_peak.header_hash
                    ):
                        self.sync_store.peer_has_block(
                            target_peak.header_hash,
                            peer.peer_node_id,
                            target_peak_response.block.weight,
                            target_peak.height,
                            False,
                        )
        else:
            if (
                curr_peak_height <= request.height
                and request.height <= curr_peak_height + self.config["short_sync_blocks_behind_threshold"]
            ):
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

            if (
                curr_peak_height <= request.height
                and request.height < curr_peak_height + self.config["sync_blocks_behind_threshold"]
            ):
                # This case of being behind but not by so much
                if await self.short_sync_batch(peer, uint32(max(curr_peak_height - 6, 0)), request.height):
                    return None

            # Clean up task reference list (used to prevent gc from killing running tasks)
            for oldtask in self._sync_task_list[:]:
                if oldtask.done():
                    self._sync_task_list.remove(oldtask)

            # This is the either the case where we were not able to sync successfully (for example, due to the fork
            # point being in the past), or we are very far behind. Performs a long sync.
            # Multiple tasks may be created here. If we don't save all handles, a task could enter a sync object
            # and be cleaned up by the GC, corrupting the sync object and possibly not allowing anything else in.
            self._sync_task_list.append(create_referenced_task(self._sync()))

    async def send_peak_to_timelords(
        self, peak_block: Optional[FullBlock] = None, peer: Optional[WSChiaConnection] = None
    ) -> None:
        """
        Sends current peak to timelords
        """
        if peak_block is None:
            peak_block = await self.blockchain.get_full_peak()
        if peak_block is not None:
            peak = self.blockchain.block_record(peak_block.header_hash)
            difficulty = self.blockchain.get_next_sub_slot_iters_and_difficulty(peak.header_hash, False)[1]
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

    async def synced(self, block_is_current_at: Optional[uint64] = None) -> bool:
        if block_is_current_at is None:
            block_is_current_at = uint64(int(time.time() - 60 * 7))
        if "simulator" in str(self.config.get("selected_network")):
            return True  # sim is always synced because it has no peers
        curr: Optional[BlockRecord] = self.blockchain.get_peak()
        if curr is None:
            return False

        while curr is not None and not curr.is_transaction_block:
            curr = self.blockchain.try_block_record(curr.prev_hash)

        if (
            curr is None
            or curr.timestamp is None
            or curr.timestamp < block_is_current_at
            or self.sync_store.get_sync_mode()
        ):
            return False
        else:
            return True

    async def on_connect(self, connection: WSChiaConnection) -> None:
        """
        Whenever we connect to another node / wallet, send them our current heads. Also send heads to farmers
        and challenges to timelords.
        """

        self._state_changed("add_connection")
        self._state_changed("sync_mode")
        # TODO: this can probably be improved
        if self.full_node_peers is not None:
            create_referenced_task(self.full_node_peers.on_connect(connection))

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

    async def on_disconnect(self, connection: WSChiaConnection) -> None:
        self.log.info(f"peer disconnected {connection.get_peer_logging()}")
        self._state_changed("close_connection")
        self._state_changed("sync_mode")
        if self.sync_store is not None:
            self.sync_store.peer_disconnected(connection.peer_node_id)
        # Remove all ph | coin id subscription for this peer
        self.subscriptions.remove_peer(connection.peer_node_id)

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
        # Ensure we are only syncing once and not double calling this method
        fork_point: Optional[uint32] = None
        if self.sync_store.get_sync_mode():
            return None

        if self.sync_store.get_long_sync():
            self.log.debug("already in long sync")
            return None

        self.sync_store.set_long_sync(True)
        self.log.debug("long sync started")
        try:
            self.log.info("Starting to perform sync.")

            # Wait until we have 3 peaks or up to a max of 30 seconds
            max_iterations = int(self.config.get("max_sync_wait", 30)) * 10

            self.log.info(f"Waiting to receive peaks from peers. (timeout: {max_iterations / 10}s)")
            peaks = []
            for i in range(max_iterations):
                peaks = [peak.header_hash for peak in self.sync_store.get_peak_of_each_peer().values()]
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

            self.sync_store.target_peak = target_peak

            self.log.info(f"Selected peak {target_peak}")
            # Check which peers are updated to this height

            peers = self.server.get_connections(NodeType.FULL_NODE)
            coroutines = []
            for peer in peers:
                coroutines.append(
                    peer.call_api(
                        FullNodeAPI.request_block,
                        full_node_protocol.RequestBlock(target_peak.height, True),
                        timeout=10,
                    )
                )
            for i, target_peak_response in enumerate(await asyncio.gather(*coroutines)):
                if (
                    target_peak_response is not None
                    and isinstance(target_peak_response, RespondBlock)
                    and target_peak_response.block.header_hash == target_peak.header_hash
                ):
                    self.sync_store.peer_has_block(
                        target_peak.header_hash, peers[i].peer_node_id, target_peak.weight, target_peak.height, False
                    )
            # TODO: disconnect from peer which gave us the heaviest_peak, if nobody has the peak
            fork_point, summaries = await self.request_validate_wp(
                target_peak.header_hash, target_peak.height, target_peak.weight
            )
            # Ensures that the fork point does not change
            async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
                await self.blockchain.warmup(fork_point)
                fork_point = await check_fork_next_block(
                    self.blockchain,
                    fork_point,
                    self.get_peers_with_peak(target_peak.header_hash),
                    node_next_block_check,
                )
                await self.sync_from_fork_point(fork_point, target_peak.height, target_peak.header_hash, summaries)
        except asyncio.CancelledError:
            self.log.warning("Syncing failed, CancelledError")
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Error with syncing: {type(e)}{tb}")
        finally:
            if self._shut_down:
                return None
            await self._finish_sync(fork_point)

    async def request_validate_wp(
        self, peak_header_hash: bytes32, peak_height: uint32, peak_weight: uint128
    ) -> tuple[uint32, list[SubEpochSummary]]:
        if self.weight_proof_handler is None:
            raise RuntimeError("Weight proof handler is None")
        peers_with_peak = self.get_peers_with_peak(peak_header_hash)
        # Request weight proof from a random peer
        peers_with_peak_len = len(peers_with_peak)
        self.log.info(f"Total of {peers_with_peak_len} peers with peak {peak_height}")
        # We can't choose from an empty sequence
        if peers_with_peak_len == 0:
            raise RuntimeError(f"Not performing sync, no peers with peak {peak_height}")
        weight_proof_peer: WSChiaConnection = random.choice(peers_with_peak)
        self.log.info(
            f"Requesting weight proof from peer {weight_proof_peer.peer_info.host} up to height {peak_height}"
        )
        cur_peak: Optional[BlockRecord] = self.blockchain.get_peak()
        if cur_peak is not None and peak_weight <= cur_peak.weight:
            raise ValueError("Not performing sync, already caught up.")
        wp_timeout = 360
        if "weight_proof_timeout" in self.config:
            wp_timeout = self.config["weight_proof_timeout"]
        self.log.debug(f"weight proof timeout is {wp_timeout} sec")
        request = full_node_protocol.RequestProofOfWeight(peak_height, peak_header_hash)
        response = await weight_proof_peer.call_api(FullNodeAPI.request_proof_of_weight, request, timeout=wp_timeout)
        # Disconnect from this peer, because they have not behaved properly
        if response is None or not isinstance(response, full_node_protocol.RespondProofOfWeight):
            await weight_proof_peer.close(600)
            raise RuntimeError(f"Weight proof did not arrive in time from peer: {weight_proof_peer.peer_info.host}")
        if response.wp.recent_chain_data[-1].reward_chain_block.height != peak_height:
            await weight_proof_peer.close(600)
            raise RuntimeError(f"Weight proof had the wrong height: {weight_proof_peer.peer_info.host}")
        if response.wp.recent_chain_data[-1].reward_chain_block.weight != peak_weight:
            await weight_proof_peer.close(600)
            raise RuntimeError(f"Weight proof had the wrong weight: {weight_proof_peer.peer_info.host}")
        if self.in_bad_peak_cache(response.wp):
            raise ValueError("Weight proof failed bad peak cache validation")
        # dont sync to wp if local peak is heavier,
        # dont ban peer, we asked for this peak
        current_peak = self.blockchain.get_peak()
        if current_peak is not None:
            if response.wp.recent_chain_data[-1].reward_chain_block.weight <= current_peak.weight:
                raise RuntimeError(
                    f"current peak is heavier than Weight proof peek: {weight_proof_peer.peer_info.host}"
                )
        try:
            validated, fork_point, summaries = await self.weight_proof_handler.validate_weight_proof(response.wp)
        except Exception as e:
            await weight_proof_peer.close(600)
            raise ValueError(f"Weight proof validation threw an error {e}")
        if not validated:
            await weight_proof_peer.close(600)
            raise ValueError("Weight proof validation failed")
        self.log.info(f"Re-checked peers: total of {len(peers_with_peak)} peers with peak {peak_height}")
        self.sync_store.set_sync_mode(True)
        self._state_changed("sync_mode")
        return fork_point, summaries

    async def sync_from_fork_point(
        self,
        fork_point_height: uint32,
        target_peak_sb_height: uint32,
        peak_hash: bytes32,
        summaries: list[SubEpochSummary],
    ) -> None:
        self.log.info(f"Start syncing from fork point at {fork_point_height} up to {target_peak_sb_height}")
        batch_size = self.constants.MAX_BLOCK_COUNT_PER_REQUESTS
        counter = 0
        if fork_point_height != 0:
            # warmup the cache
            curr = self.blockchain.height_to_block_record(fork_point_height)
            while (
                curr.sub_epoch_summary_included is None
                or counter < 3 * self.constants.MAX_SUB_SLOT_BLOCKS + self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK + 3
            ):
                res = await self.blockchain.get_block_record_from_db(curr.prev_hash)
                if res is None:
                    break
                curr = res
                self.blockchain.add_block_record(curr)
                counter += 1

        # normally "fork_point" or "fork_height" refers to the first common
        # block between the main chain and the fork. Here "fork_point_height"
        # seems to refer to the first diverging block
        # in case we're validating a reorg fork (i.e. not extending the
        # main chain), we need to record the coin set from that fork in
        # fork_info. Otherwise validation is very expensive, especially
        # for deep reorgs
        if fork_point_height > 0:
            fork_hash = self.blockchain.height_to_hash(uint32(fork_point_height - 1))
            assert fork_hash is not None
        else:
            fork_hash = self.constants.GENESIS_CHALLENGE
        fork_info = ForkInfo(fork_point_height - 1, fork_point_height - 1, fork_hash)

        if fork_point_height == 0:
            ssi = self.constants.SUB_SLOT_ITERS_STARTING
            diff = self.constants.DIFFICULTY_STARTING
            prev_ses_block = None
        else:
            prev_b_hash = self.blockchain.height_to_hash(fork_point_height)
            assert prev_b_hash is not None
            prev_b = await self.blockchain.get_full_block(prev_b_hash)
            assert prev_b is not None
            ssi, diff, prev_ses_block = await self.get_sub_slot_iters_difficulty_ses_block(prev_b, None, None)

        # we need an augmented blockchain to validate blocks in batches. The
        # batch must be treated as if it's part of the chain to validate the
        # blocks in it. We also need them to keep appearing as if they're part
        # of the chain when pipelining the validation of blocks. We start
        # validating the next batch while still adding the first batch to the
        # chain.
        blockchain = AugmentedBlockchain(self.blockchain)
        peers_with_peak: list[WSChiaConnection] = self.get_peers_with_peak(peak_hash)

        async def fetch_blocks(output_queue: asyncio.Queue[Optional[tuple[WSChiaConnection, list[FullBlock]]]]) -> None:
            # the rate limit for respond_blocks is 100 messages / 60 seconds.
            # But the limit is scaled to 30% for outbound messages, so that's 30
            # messages per 60 seconds.
            # That's 2 seconds per request.
            seconds_per_request = 2
            start_height, end_height = 0, 0

            # the timestamp of when the next request_block message is allowed to
            # be sent. It's initialized to the current time, and bumped by the
            # seconds_per_request every time we send a request. This ensures we
            # won't exceed the 100 requests / 60 seconds rate limit.
            # Whichever peer has the lowest timestamp is the one we request
            # from. peers that take more than 5 seconds to respond are pushed to
            # the end of the queue, to be less likely to request from.

            # This should be cleaned up to not be a hard coded value, and maybe
            # allow higher request rates (and align the request_blocks and
            # respond_blocks rate limits).
            now = time.monotonic()
            new_peers_with_peak: list[tuple[WSChiaConnection, float]] = [(c, now) for c in peers_with_peak[:]]
            self.log.info(f"peers with peak: {len(new_peers_with_peak)}")
            random.shuffle(new_peers_with_peak)
            try:
                # block request ranges are *inclusive*, this requires some
                # gymnastics of this range (+1 to make it exclusive, like normal
                # ranges) and then -1 when forming the request message
                for start_height in range(fork_point_height, target_peak_sb_height + 1, batch_size):
                    end_height = min(target_peak_sb_height, start_height + batch_size - 1)
                    request = RequestBlocks(uint32(start_height), uint32(end_height), True)
                    new_peers_with_peak.sort(key=lambda pair: pair[1])
                    fetched = False
                    for idx, (peer, timestamp) in enumerate(new_peers_with_peak):
                        if peer.closed:
                            continue

                        start = time.monotonic()
                        if start < timestamp:
                            # rate limit ourselves, since we sent a message to
                            # this peer too recently
                            await asyncio.sleep(timestamp - start)
                            start = time.monotonic()

                        # update the timestamp, now that we're sending a request
                        # it's OK for the timestamp to fall behind wall-clock
                        # time. It just means we're allowed to send more
                        # requests to catch up
                        if is_localhost(peer.peer_info.host):
                            # we don't apply rate limits to localhost, and our
                            # tests depend on it
                            bump = 0.1
                        else:
                            bump = seconds_per_request

                        new_peers_with_peak[idx] = (
                            new_peers_with_peak[idx][0],
                            new_peers_with_peak[idx][1] + bump,
                        )
                        # the fewer peers we have, the more willing we should be
                        # to wait for them.
                        timeout = int(30 + 30 / len(new_peers_with_peak))
                        response = await peer.call_api(FullNodeAPI.request_blocks, request, timeout=timeout)
                        end = time.monotonic()
                        if response is None:
                            self.log.info(f"peer timed out after {end - start:.1f} s")
                            await peer.close()
                        elif isinstance(response, RespondBlocks):
                            if end - start > 5:
                                self.log.info(f"peer took {end - start:.1f} s to respond to request_blocks")
                                # this isn't a great peer, reduce its priority
                                # to prefer any peers that had to wait for it.
                                # By setting the next allowed timestamp to now,
                                # means that any other peer that has waited for
                                # this will have its next allowed timestamp in
                                # the passed, and be preferred multiple times
                                # over this peer.
                                new_peers_with_peak[idx] = (
                                    new_peers_with_peak[idx][0],
                                    end,
                                )
                            start = time.monotonic()
                            await output_queue.put((peer, response.blocks))
                            end = time.monotonic()
                            if end - start > 1:
                                self.log.info(
                                    f"sync pipeline back-pressure. stalled {end - start:0.2f} "
                                    "seconds on prevalidate block"
                                )
                            fetched = True
                            break
                    if fetched is False:
                        self.log.error(f"failed fetching {start_height} to {end_height} from peers")
                        return
                    if self.sync_store.peers_changed.is_set():
                        existing_peers = {id(c): timestamp for c, timestamp in new_peers_with_peak}
                        peers = self.get_peers_with_peak(peak_hash)
                        new_peers_with_peak = [(c, existing_peers.get(id(c), end)) for c in peers]
                        random.shuffle(new_peers_with_peak)
                        self.sync_store.peers_changed.clear()
                        self.log.info(f"peers with peak: {len(new_peers_with_peak)}")
            except Exception as e:
                self.log.error(f"Exception fetching {start_height} to {end_height} from peer {e}")
            finally:
                # finished signal with None
                await output_queue.put(None)

        async def validate_blocks(
            input_queue: asyncio.Queue[Optional[tuple[WSChiaConnection, list[FullBlock]]]],
            output_queue: asyncio.Queue[
                Optional[
                    tuple[WSChiaConnection, ValidationState, list[Awaitable[PreValidationResult]], list[FullBlock]]
                ]
            ],
        ) -> None:
            nonlocal blockchain
            nonlocal fork_info
            first_batch = True

            vs = ValidationState(ssi, diff, prev_ses_block)

            try:
                while True:
                    res: Optional[tuple[WSChiaConnection, list[FullBlock]]] = await input_queue.get()
                    if res is None:
                        self.log.debug("done fetching blocks")
                        return None
                    peer, blocks = res

                    # skip_blocks is only relevant at the start of the sync,
                    # to skip blocks we already have in the database (and have
                    # been validated). Once we start validating blocks, we
                    # shouldn't be skipping any.
                    blocks_to_validate = await self.skip_blocks(blockchain, blocks, fork_info, vs)
                    assert first_batch or len(blocks_to_validate) == len(blocks)
                    next_validation_state = copy.copy(vs)

                    if len(blocks_to_validate) == 0:
                        continue

                    first_batch = False

                    futures: list[Awaitable[PreValidationResult]] = []
                    for block in blocks_to_validate:
                        futures.extend(
                            await self.prevalidate_blocks(
                                blockchain,
                                [block],
                                vs,
                                summaries,
                            )
                        )
                    start = time.monotonic()
                    await output_queue.put((peer, next_validation_state, list(futures), blocks_to_validate))
                    end = time.monotonic()
                    if end - start > 1:
                        self.log.info(f"sync pipeline back-pressure. stalled {end - start:0.2f} seconds on add_block()")
            except Exception:
                self.log.exception("Exception validating")
            finally:
                # finished signal with None
                await output_queue.put(None)

        async def ingest_blocks(
            input_queue: asyncio.Queue[
                Optional[
                    tuple[WSChiaConnection, ValidationState, list[Awaitable[PreValidationResult]], list[FullBlock]]
                ]
            ],
        ) -> None:
            nonlocal fork_info
            block_rate = 0.0
            block_rate_time = time.monotonic()
            block_rate_height = -1
            while True:
                res = await input_queue.get()
                if res is None:
                    self.log.debug("done validating blocks")
                    return None
                peer, vs, futures, blocks = res
                start_height = blocks[0].height
                end_height = blocks[-1].height

                if block_rate_height == -1:
                    block_rate_height = start_height

                pre_validation_results = list(await asyncio.gather(*futures))
                # The ValidationState object (vs) is an in-out parameter. the add_block_batch()
                # call will update it
                state_change_summary, err = await self.add_prevalidated_blocks(
                    blockchain,
                    blocks,
                    pre_validation_results,
                    fork_info,
                    peer.peer_info,
                    vs,
                )
                if err is not None:
                    await peer.close(600)
                    raise ValueError(f"Failed to validate block batch {start_height} to {end_height}: {err}")
                if end_height - block_rate_height > 100:
                    now = time.monotonic()
                    block_rate = (end_height - block_rate_height) / (now - block_rate_time)
                    block_rate_time = now
                    block_rate_height = end_height

                self.log.info(
                    f"Added blocks {start_height} to {end_height} "
                    f"({block_rate:.3g} blocks/s) (from: {peer.peer_info.ip})"
                )
                peak: Optional[BlockRecord] = self.blockchain.get_peak()
                if state_change_summary is not None:
                    assert peak is not None
                    # Hints must be added to the DB. The other post-processing tasks are not required when syncing
                    hints_to_add, _ = get_hints_and_subscription_coin_ids(
                        state_change_summary,
                        self.subscriptions.has_coin_subscription,
                        self.subscriptions.has_puzzle_subscription,
                    )
                    await self.hint_store.add_hints(hints_to_add)
                # Note that end_height is not necessarily the peak at this
                # point. In case of a re-org, it may even be significantly
                # higher than _peak_height, and still not be the peak.
                # clean_block_record() will not necessarily honor this cut-off
                # height, in that case.
                self.blockchain.clean_block_record(end_height - self.constants.BLOCKS_CACHE_SIZE)

        block_queue: asyncio.Queue[Optional[tuple[WSChiaConnection, list[FullBlock]]]] = asyncio.Queue(maxsize=10)
        validation_queue: asyncio.Queue[
            Optional[tuple[WSChiaConnection, ValidationState, list[Awaitable[PreValidationResult]], list[FullBlock]]]
        ] = asyncio.Queue(maxsize=10)

        fetch_task = create_referenced_task(fetch_blocks(block_queue))
        validate_task = create_referenced_task(validate_blocks(block_queue, validation_queue))
        ingest_task = create_referenced_task(ingest_blocks(validation_queue))
        try:
            await asyncio.gather(fetch_task, validate_task, ingest_task)
        except Exception:
            self.log.exception("sync from fork point failed")
        finally:
            cancel_task_safe(validate_task, self.log)
            cancel_task_safe(fetch_task)
            cancel_task_safe(ingest_task)

            # we still need to await all the pending futures of the
            # prevalidation steps posted to the thread pool
            while not validation_queue.empty():
                result = validation_queue.get_nowait()
                if result is None:
                    continue

                _, _, futures, _ = result
                await asyncio.gather(*futures)

    def get_peers_with_peak(self, peak_hash: bytes32) -> list[WSChiaConnection]:
        peer_ids: set[bytes32] = self.sync_store.get_peers_that_have_peak([peak_hash])
        if len(peer_ids) == 0:
            self.log.warning(f"Not syncing, no peers with header_hash {peak_hash} ")
            return []
        return [c for c in self.server.all_connections.values() if c.peer_node_id in peer_ids]

    async def _wallets_sync_task_handler(self) -> None:
        while not self._shut_down:
            try:
                wallet_update = await self.wallet_sync_queue.get()
                await self.update_wallets(wallet_update)
            except Exception:
                self.log.exception("Wallet sync task failure")
                continue

    async def update_wallets(self, wallet_update: WalletUpdate) -> None:
        self.log.debug(
            f"update_wallets - fork_height: {wallet_update.fork_height}, peak_height: {wallet_update.peak.height}"
        )
        changes_for_peer: dict[bytes32, set[CoinState]] = {}
        for coin_record in wallet_update.coin_records:
            coin_id = coin_record.name
            subscribed_peers = self.subscriptions.peers_for_coin_id(coin_id)
            subscribed_peers.update(self.subscriptions.peers_for_puzzle_hash(coin_record.coin.puzzle_hash))
            hint = wallet_update.hints.get(coin_id)
            if hint is not None:
                subscribed_peers.update(self.subscriptions.peers_for_puzzle_hash(hint))
            for peer in subscribed_peers:
                changes_for_peer.setdefault(peer, set()).add(coin_record.coin_state)

        for peer, changes in changes_for_peer.items():
            connection = self.server.all_connections.get(peer)
            if connection is not None:
                state = CoinStateUpdate(
                    wallet_update.peak.height,
                    wallet_update.fork_height,
                    wallet_update.peak.header_hash,
                    list(changes),
                )
                await connection.send_message(make_msg(ProtocolMessageTypes.coin_state_update, state))

        # Tell wallets about the new peak
        new_peak_message = make_msg(
            ProtocolMessageTypes.new_peak_wallet,
            wallet_protocol.NewPeakWallet(
                wallet_update.peak.header_hash,
                wallet_update.peak.height,
                wallet_update.peak.weight,
                wallet_update.fork_height,
            ),
        )
        await self.server.send_to_all([new_peak_message], NodeType.WALLET)

    async def add_block_batch(
        self,
        all_blocks: list[FullBlock],
        peer_info: PeerInfo,
        fork_info: ForkInfo,
        vs: ValidationState,  # in-out parameter
        blockchain: AugmentedBlockchain,
        wp_summaries: Optional[list[SubEpochSummary]] = None,
    ) -> tuple[bool, Optional[StateChangeSummary]]:
        # Precondition: All blocks must be contiguous blocks, index i+1 must be the parent of index i
        # Returns a bool for success, as well as a StateChangeSummary if the peak was advanced

        pre_validate_start = time.monotonic()
        blocks_to_validate = await self.skip_blocks(blockchain, all_blocks, fork_info, vs)

        if len(blocks_to_validate) == 0:
            return True, None

        futures = await self.prevalidate_blocks(
            blockchain,
            blocks_to_validate,
            copy.copy(vs),
            wp_summaries,
        )
        pre_validation_results = list(await asyncio.gather(*futures))

        agg_state_change_summary, err = await self.add_prevalidated_blocks(
            blockchain,
            blocks_to_validate,
            pre_validation_results,
            fork_info,
            peer_info,
            vs,
        )

        if agg_state_change_summary is not None:
            self._state_changed("new_peak")
            self.log.debug(
                f"Total time for {len(blocks_to_validate)} blocks: {time.monotonic() - pre_validate_start}, "
                f"advanced: True"
            )
        return err is None, agg_state_change_summary

    async def skip_blocks(
        self,
        blockchain: AugmentedBlockchain,
        all_blocks: list[FullBlock],
        fork_info: ForkInfo,
        vs: ValidationState,  # in-out parameter
    ) -> list[FullBlock]:
        blocks_to_validate: list[FullBlock] = []
        for i, block in enumerate(all_blocks):
            header_hash = block.header_hash
            block_rec = await blockchain.get_block_record_from_db(header_hash)
            if block_rec is None:
                blocks_to_validate = all_blocks[i:]
                break
            else:
                blockchain.add_block_record(block_rec)
                if block_rec.sub_epoch_summary_included:
                    # already validated block, update sub slot iters, difficulty and prev sub epoch summary
                    vs.prev_ses_block = block_rec
                    if block_rec.sub_epoch_summary_included.new_sub_slot_iters is not None:
                        vs.ssi = block_rec.sub_epoch_summary_included.new_sub_slot_iters
                    if block_rec.sub_epoch_summary_included.new_difficulty is not None:
                        vs.difficulty = block_rec.sub_epoch_summary_included.new_difficulty

            # the below section updates the fork_info object, if
            # there is one.
            if block.height <= fork_info.peak_height:
                continue
            # we have already validated this block once, no need to do it again.
            # however, if this block is not part of the main chain, we need to
            # update the fork context with its additions and removals
            if self.blockchain.height_to_hash(block.height) == header_hash:
                # we're on the main chain, just fast-forward the fork height
                fork_info.reset(block.height, header_hash)
            else:
                # We have already validated the block, but if it's not part of the
                # main chain, we still need to re-run it to update the additions and
                # removals in fork_info.
                await self.blockchain.advance_fork_info(block, fork_info)
                await self.blockchain.run_single_block(block, fork_info)
        return blocks_to_validate

    async def prevalidate_blocks(
        self,
        blockchain: AugmentedBlockchain,
        blocks_to_validate: list[FullBlock],
        vs: ValidationState,
        wp_summaries: Optional[list[SubEpochSummary]] = None,
    ) -> Sequence[Awaitable[PreValidationResult]]:
        """
        This is a thin wrapper over pre_validate_block().

        Args:
            blockchain:
            blocks_to_validate:
            vs: The ValidationState for the first block in the batch. This is an in-out
                parameter. It will be updated to be the validation state for the next
                batch of blocks.
            wp_summaries:
        """
        # Validates signatures in multiprocessing since they take a while, and we don't have cached transactions
        # for these blocks (unlike during normal operation where we validate one at a time)
        # We have to copy the ValidationState object to preserve it for the add_block()
        # call below. pre_validate_block() will update the
        # object we pass in.
        ret: list[Awaitable[PreValidationResult]] = []
        for block in blocks_to_validate:
            ret.append(
                await pre_validate_block(
                    self.constants,
                    blockchain,
                    block,
                    self.blockchain.pool,
                    None,
                    vs,
                    wp_summaries=wp_summaries,
                )
            )
        return ret

    async def add_prevalidated_blocks(
        self,
        blockchain: AugmentedBlockchain,
        blocks_to_validate: list[FullBlock],
        pre_validation_results: list[PreValidationResult],
        fork_info: ForkInfo,
        peer_info: PeerInfo,
        vs: ValidationState,  # in-out parameter
    ) -> tuple[Optional[StateChangeSummary], Optional[Err]]:
        agg_state_change_summary: Optional[StateChangeSummary] = None
        block_record = await self.blockchain.get_block_record_from_db(blocks_to_validate[0].prev_header_hash)
        for i, block in enumerate(blocks_to_validate):
            header_hash = block.header_hash
            assert vs.prev_ses_block is None or vs.prev_ses_block.height < block.height
            assert pre_validation_results[i].required_iters is not None
            state_change_summary: Optional[StateChangeSummary]
            # when adding blocks in batches, we won't have any overlapping
            # signatures with the mempool. There won't be any cache hits, so
            # there's no need to pass the BLS cache in

            if len(block.finished_sub_slots) > 0:
                cc_sub_slot = block.finished_sub_slots[0].challenge_chain
                if cc_sub_slot.new_sub_slot_iters is not None or cc_sub_slot.new_difficulty is not None:
                    expected_sub_slot_iters, expected_difficulty = get_next_sub_slot_iters_and_difficulty(
                        self.constants, True, block_record, blockchain
                    )
                    assert cc_sub_slot.new_sub_slot_iters is not None
                    vs.ssi = cc_sub_slot.new_sub_slot_iters
                    assert cc_sub_slot.new_difficulty is not None
                    vs.difficulty = cc_sub_slot.new_difficulty
                    assert expected_sub_slot_iters == vs.ssi
                    assert expected_difficulty == vs.difficulty
            block_rec = blockchain.block_record(block.header_hash)
            result, error, state_change_summary = await self.blockchain.add_block(
                block,
                pre_validation_results[i],
                vs.ssi,
                fork_info,
                prev_ses_block=vs.prev_ses_block,
                block_record=block_rec,
            )
            if error is None:
                blockchain.remove_extra_block(header_hash)

            if result == AddBlockResult.NEW_PEAK:
                # since this block just added a new peak, we've don't need any
                # fork history from fork_info anymore
                fork_info.reset(block.height, header_hash)
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
                        agg_state_change_summary.removals + state_change_summary.removals,
                        agg_state_change_summary.additions + state_change_summary.additions,
                        agg_state_change_summary.new_rewards + state_change_summary.new_rewards,
                    )
            elif result in {AddBlockResult.INVALID_BLOCK, AddBlockResult.DISCONNECTED_BLOCK}:
                if error is not None:
                    self.log.error(f"Error: {error}, Invalid block from peer: {peer_info} ")
                return agg_state_change_summary, error
            block_record = blockchain.block_record(header_hash)
            assert block_record is not None
            if block_record.sub_epoch_summary_included is not None:
                vs.prev_ses_block = block_record
                if self.weight_proof_handler is not None:
                    await self.weight_proof_handler.create_prev_sub_epoch_segments()
        if agg_state_change_summary is not None:
            self._state_changed("new_peak")
        return agg_state_change_summary, None

    async def get_sub_slot_iters_difficulty_ses_block(
        self, block: FullBlock, ssi: Optional[uint64], diff: Optional[uint64]
    ) -> tuple[uint64, uint64, Optional[BlockRecord]]:
        prev_ses_block = None
        if ssi is None or diff is None:
            if block.height == 0:
                ssi = self.constants.SUB_SLOT_ITERS_STARTING
                diff = self.constants.DIFFICULTY_STARTING
        if ssi is None or diff is None:
            if len(block.finished_sub_slots) > 0:
                if block.finished_sub_slots[0].challenge_chain.new_difficulty is not None:
                    diff = block.finished_sub_slots[0].challenge_chain.new_difficulty
                if block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:
                    ssi = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters

        if block.height > 0:
            prev_b = await self.blockchain.get_block_record_from_db(block.prev_header_hash)
            curr = prev_b
            while prev_ses_block is None or ssi is None or diff is None:
                assert curr is not None
                if curr.height == 0:
                    if ssi is None or diff is None:
                        ssi = self.constants.SUB_SLOT_ITERS_STARTING
                        diff = self.constants.DIFFICULTY_STARTING
                    if prev_ses_block is None:
                        prev_ses_block = curr
                if curr.sub_epoch_summary_included is not None:
                    if prev_ses_block is None:
                        prev_ses_block = curr
                    if ssi is None or diff is None:
                        if curr.sub_epoch_summary_included.new_difficulty is not None:
                            diff = curr.sub_epoch_summary_included.new_difficulty
                        if curr.sub_epoch_summary_included.new_sub_slot_iters is not None:
                            ssi = curr.sub_epoch_summary_included.new_sub_slot_iters
                curr = await self.blockchain.get_block_record_from_db(curr.prev_hash)
        assert ssi is not None
        assert diff is not None
        return ssi, diff, prev_ses_block

    async def _finish_sync(self, fork_point: Optional[uint32]) -> None:
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

        async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
            peak: Optional[BlockRecord] = self.blockchain.get_peak()
            peak_fb: Optional[FullBlock] = await self.blockchain.get_full_peak()
            if peak_fb is not None:
                if fork_point is None:
                    fork_point = uint32(max(peak_fb.height - 1, 0))
                assert peak is not None
                state_change_summary = StateChangeSummary(peak, fork_point, [], [], [], [])
                ppp_result: PeakPostProcessingResult = await self.peak_post_processing(
                    peak_fb, state_change_summary, None
                )

        if peak_fb is not None:
            # Call outside of priority_mutex to encourage concurrency
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
            assert block.foliage.foliage_block_data.pool_signature is not None
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
        peer: WSChiaConnection,
        ip_sub_slot: Optional[EndOfSubSlotBundle],
    ) -> None:
        self.log.info(
            f"⏲️  Finished signage point {request.index_from_challenge}/"
            f"{self.constants.NUM_SPS_SUB_SLOT}: "
            f"CC: {request.challenge_chain_vdf.output.get_hash().hex()} "
            f"RC: {request.reward_chain_vdf.output.get_hash().hex()} "
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
        await self.server.send_to_all([msg], NodeType.FULL_NODE, peer.peer_node_id)

        peak = self.blockchain.get_peak()
        if peak is not None and peak.height > self.constants.MAX_SUB_SLOT_BLOCKS:
            sub_slot_iters = peak.sub_slot_iters
            difficulty = uint64(peak.weight - self.blockchain.block_record(peak.prev_hash).weight)
            # Makes sure to potentially update the difficulty if we are past the peak (into a new sub-slot)
            assert ip_sub_slot is not None
            if request.challenge_chain_vdf.challenge != ip_sub_slot.challenge_chain.get_hash():
                sub_slot_iters, difficulty = self.blockchain.get_next_sub_slot_iters_and_difficulty(
                    peak.header_hash, True
                )
        else:
            difficulty = self.constants.DIFFICULTY_STARTING
            sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING

        tx_peak = self.blockchain.get_tx_peak()
        # Notify farmers of the new signage point
        broadcast_farmer = farmer_protocol.NewSignagePoint(
            request.challenge_chain_vdf.challenge,
            request.challenge_chain_vdf.output.get_hash(),
            request.reward_chain_vdf.output.get_hash(),
            difficulty,
            sub_slot_iters,
            request.index_from_challenge,
            uint32(0) if peak is None else peak.height,
            tx_peak.height if tx_peak is not None else uint32(0),
            sp_source_data=SignagePointSourceData(
                vdf_data=SPVDFSourceData(request.challenge_chain_vdf.output, request.reward_chain_vdf.output)
            ),
        )
        msg = make_msg(ProtocolMessageTypes.new_signage_point, broadcast_farmer)
        await self.server.send_to_all([msg], NodeType.FARMER)

        self._state_changed("signage_point", {"broadcast_farmer": broadcast_farmer})

    async def peak_post_processing(
        self,
        block: FullBlock,
        state_change_summary: StateChangeSummary,
        peer: Optional[WSChiaConnection],
    ) -> PeakPostProcessingResult:
        """
        Must be called under self.blockchain.priority_mutex. This updates the internal state of the full node with the
        latest peak information. It also notifies peers about the new peak.
        """

        record = state_change_summary.peak
        sub_slot_iters, difficulty = self.blockchain.get_next_sub_slot_iters_and_difficulty(record.header_hash, False)

        self.log.info(
            f"🌱 Updated peak to height {record.height}, weight {record.weight}, "
            f"hh {record.header_hash.hex()}, "
            f"ph {record.prev_hash.hex()}, "
            f"forked at {state_change_summary.fork_height}, rh: {record.reward_infusion_new_challenge.hex()}, "
            f"total iters: {record.total_iters}, "
            f"overflow: {record.overflow}, "
            f"deficit: {record.deficit}, "
            f"difficulty: {difficulty}, "
            f"sub slot iters: {sub_slot_iters}, "
            f"Generator size: "
            f"{len(bytes(block.transactions_generator)) if block.transactions_generator else 'No tx'}, "
            f"Generator ref list size: "
            f"{len(block.transactions_generator_ref_list) if block.transactions_generator else 'No tx'}"
        )

        hints_to_add, lookup_coin_ids = get_hints_and_subscription_coin_ids(
            state_change_summary,
            self.subscriptions.has_coin_subscription,
            self.subscriptions.has_puzzle_subscription,
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
            fork_block = await self.blockchain.get_block_record_from_db(fork_hash)

        fns_peak_result: FullNodeStorePeakResult = self.full_node_store.new_peak(
            record,
            block,
            sub_slots[0],
            sub_slots[1],
            fork_block,
            self.blockchain,
            sub_slot_iters,
            difficulty,
        )

        signage_points: list[tuple[RespondSignagePoint, WSChiaConnection, Optional[EndOfSubSlotBundle]]] = []
        if fns_peak_result.new_signage_points is not None and peer is not None:
            for index, sp in fns_peak_result.new_signage_points:
                assert (
                    sp.cc_vdf is not None
                    and sp.cc_proof is not None
                    and sp.rc_vdf is not None
                    and sp.rc_proof is not None
                )
                # Collect the data for networking outside the mutex
                signage_points.append(
                    (
                        RespondSignagePoint(index, sp.cc_vdf, sp.cc_proof, sp.rc_vdf, sp.rc_proof),
                        peer,
                        sub_slots[1],
                    )
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
        spent_coins: list[bytes32] = [coin_id for coin_id, _ in state_change_summary.removals]
        mempool_new_peak_result = await self.mempool_manager.new_peak(self.blockchain.get_tx_peak(), spent_coins)

        return PeakPostProcessingResult(
            mempool_new_peak_result.items,
            mempool_new_peak_result.removals,
            fns_peak_result,
            hints_to_add,
            lookup_coin_ids,
            signage_points=signage_points,
        )

    async def peak_post_processing_2(
        self,
        block: FullBlock,
        peer: Optional[WSChiaConnection],
        state_change_summary: StateChangeSummary,
        ppp_result: PeakPostProcessingResult,
    ) -> None:
        """
        Does NOT need to be called under the blockchain lock. Handle other parts of post processing like communicating
        with peers
        """
        record = state_change_summary.peak
        for signage_point in ppp_result.signage_points:
            await self.signage_point_post_processing(*signage_point)
        for new_peak_item in ppp_result.mempool_peak_result:
            self.log.debug(f"Added transaction to mempool: {new_peak_item.transaction_id}")
            mempool_item = self.mempool_manager.get_mempool_item(new_peak_item.transaction_id)
            assert mempool_item is not None
            await self.broadcast_added_tx(mempool_item)

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
            self.full_node_store.clear_old_cache_entries()

        if self.sync_store.get_sync_mode() is False:
            await self.send_peak_to_timelords(block)
            await self.broadcast_removed_tx(ppp_result.mempool_removals)

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
                await self.server.send_to_all([msg], NodeType.FULL_NODE, peer.peer_node_id)
            else:
                await self.server.send_to_all([msg], NodeType.FULL_NODE)

        coin_hints: dict[bytes32, bytes32] = {
            coin_id: bytes32(hint) for coin_id, hint in ppp_result.hints if len(hint) == 32
        }

        peak = Peak(
            state_change_summary.peak.header_hash, state_change_summary.peak.height, state_change_summary.peak.weight
        )

        # Looks up coin records in DB for the coins that wallets are interested in
        new_states = await self.coin_store.get_coin_records(ppp_result.lookup_coin_ids)

        await self.wallet_sync_queue.put(
            WalletUpdate(
                state_change_summary.fork_height,
                peak,
                state_change_summary.rolled_back_records + new_states,
                coin_hints,
            )
        )

        self._state_changed("new_peak")

    async def add_block(
        self,
        block: FullBlock,
        peer: Optional[WSChiaConnection] = None,
        bls_cache: Optional[BLSCache] = None,
        raise_on_disconnected: bool = False,
        fork_info: Optional[ForkInfo] = None,
    ) -> Optional[Message]:
        """
        Add a full block from a peer full node (or ourselves).
        """
        if self.sync_store.get_sync_mode():
            return None

        # Adds the block to seen, and check if it's seen before (which means header is in memory)
        header_hash = block.header_hash
        if self.blockchain.contains_block(header_hash, block.height):
            if fork_info is not None:
                await self.blockchain.run_single_block(block, fork_info)
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
            foliage_hash: Optional[bytes32] = block.foliage.foliage_transaction_block_hash
            assert foliage_hash is not None
            unf_entry: Optional[UnfinishedBlockEntry] = self.full_node_store.get_unfinished_block_result(
                unfinished_rh, foliage_hash
            )
            assert unf_entry is None or unf_entry.result is None or unf_entry.result.validated_signature is True
            if (
                unf_entry is not None
                and unf_entry.unfinished_block is not None
                and unf_entry.unfinished_block.transactions_generator is not None
                and unf_entry.unfinished_block.foliage_transaction_block == block.foliage_transaction_block
            ):
                # We checked that the transaction block is the same, therefore all transactions and the signature
                # must be identical in the unfinished and finished blocks. We can therefore use the cache.

                # this is a transaction block, the foliage hash should be set
                assert foliage_hash is not None
                pre_validation_result = unf_entry.result
                assert pre_validation_result is not None
                block = block.replace(
                    transactions_generator=unf_entry.unfinished_block.transactions_generator,
                    transactions_generator_ref_list=unf_entry.unfinished_block.transactions_generator_ref_list,
                )
            else:
                # We still do not have the correct information for this block, perhaps there is a duplicate block
                # with the same unfinished block hash in the cache, so we need to fetch the correct one
                if peer is None:
                    return None

                block_response: Optional[Any] = await peer.call_api(
                    FullNodeAPI.request_block, full_node_protocol.RequestBlock(block.height, True)
                )
                if block_response is None or not isinstance(block_response, full_node_protocol.RespondBlock):
                    self.log.warning(
                        f"Was not able to fetch the correct block for height {block.height} {block_response}"
                    )
                    return None
                new_block: FullBlock = block_response.block
                if new_block.foliage_transaction_block != block.foliage_transaction_block:
                    self.log.warning(
                        f"Received the wrong block for height {block.height} {new_block.header_hash.hex()}"
                    )
                    return None
                assert new_block.transactions_generator is not None

                self.log.debug(
                    f"Wrong info in the cache for bh {new_block.header_hash.hex()}, "
                    f"there might be multiple blocks from the "
                    f"same farmer with the same pospace."
                )
                # This recursion ends here, we cannot recurse again because transactions_generator is not None
                return await self.add_block(new_block, peer, bls_cache)
        state_change_summary: Optional[StateChangeSummary] = None
        ppp_result: Optional[PeakPostProcessingResult] = None
        async with (
            self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high),
            enable_profiler(self.profile_block_validation) as pr,
        ):
            # After acquiring the lock, check again, because another asyncio thread might have added it
            if self.blockchain.contains_block(header_hash, block.height):
                if fork_info is not None:
                    await self.blockchain.run_single_block(block, fork_info)
                return None
            validation_start = time.monotonic()
            # Tries to add the block to the blockchain, if we already validated transactions, don't do it again
            conds = None
            if pre_validation_result is not None and pre_validation_result.conds is not None:
                conds = pre_validation_result.conds

            # Don't validate signatures because we want to validate them in the main thread later, since we have a
            # cache available
            prev_b = None
            prev_ses_block = None
            if block.height > 0:
                prev_b = await self.blockchain.get_block_record_from_db(block.prev_header_hash)
                assert prev_b is not None
                curr = prev_b
                while curr.height > 0 and curr.sub_epoch_summary_included is None:
                    curr = self.blockchain.block_record(curr.prev_hash)
                prev_ses_block = curr
            new_slot = len(block.finished_sub_slots) > 0
            ssi, diff = get_next_sub_slot_iters_and_difficulty(self.constants, new_slot, prev_b, self.blockchain)
            future = await pre_validate_block(
                self.blockchain.constants,
                AugmentedBlockchain(self.blockchain),
                block,
                self.blockchain.pool,
                conds,
                ValidationState(ssi, diff, prev_ses_block),
            )
            pre_validation_result = await future
            added: Optional[AddBlockResult] = None
            add_block_start = time.monotonic()
            pre_validation_time = add_block_start - validation_start
            try:
                if pre_validation_result.error is not None:
                    if Err(pre_validation_result.error) == Err.INVALID_PREV_BLOCK_HASH:
                        added = AddBlockResult.DISCONNECTED_BLOCK
                        error_code: Optional[Err] = Err.INVALID_PREV_BLOCK_HASH
                    elif Err(pre_validation_result.error) == Err.TIMESTAMP_TOO_FAR_IN_FUTURE:
                        raise TimestampError
                    else:
                        raise ValueError(
                            f"Failed to validate block {header_hash} height "
                            f"{block.height}: {Err(pre_validation_result.error).name}"
                        )
                else:
                    if fork_info is None:
                        fork_info = ForkInfo(block.height - 1, block.height - 1, block.prev_header_hash)
                    (added, error_code, state_change_summary) = await self.blockchain.add_block(
                        block, pre_validation_result, ssi, fork_info
                    )
                add_block_time = time.monotonic() - add_block_start
                if added == AddBlockResult.ALREADY_HAVE_BLOCK:
                    return None
                elif added == AddBlockResult.INVALID_BLOCK:
                    assert error_code is not None
                    self.log.error(f"Block {header_hash} at height {block.height} is invalid with code {error_code}.")
                    raise ConsensusError(error_code, [header_hash])
                elif added == AddBlockResult.DISCONNECTED_BLOCK:
                    self.log.info(f"Disconnected block {header_hash} at height {block.height}")
                    if raise_on_disconnected:
                        raise RuntimeError("Expected block to be added, received disconnected block.")
                    return None
                elif added == AddBlockResult.NEW_PEAK:
                    # Evict any related BLS cache entries as we no longer need them
                    if bls_cache is not None and pre_validation_result.conds is not None:
                        pairs_pks, pairs_msgs = pkm_pairs(
                            pre_validation_result.conds, self.constants.AGG_SIG_ME_ADDITIONAL_DATA
                        )
                        bls_cache.evict(pairs_pks, pairs_msgs)
                    # Only propagate blocks which extend the blockchain (becomes one of the heads)
                    assert state_change_summary is not None
                    post_process_time = time.monotonic()
                    ppp_result = await self.peak_post_processing(block, state_change_summary, peer)
                    post_process_time = time.monotonic() - post_process_time

                elif added == AddBlockResult.ADDED_AS_ORPHAN:
                    self.log.info(
                        f"Received orphan block of height {block.height} rh {block.reward_chain_block.get_hash()}"
                    )
                    post_process_time = 0.0
                else:
                    # Should never reach here, all the cases are covered
                    raise RuntimeError(f"Invalid result from add_block {added}")
            except asyncio.CancelledError:
                # We need to make sure to always call this method even when we get a cancel exception, to make sure
                # the node stays in sync
                if added == AddBlockResult.NEW_PEAK:
                    assert state_change_summary is not None
                    await self.peak_post_processing(block, state_change_summary, peer)
                raise

            validation_time = time.monotonic() - validation_start

        if ppp_result is not None:
            assert state_change_summary is not None
            post_process_time2 = time.monotonic()
            await self.peak_post_processing_2(block, peer, state_change_summary, ppp_result)
            post_process_time2 = time.monotonic() - post_process_time2
        else:
            post_process_time2 = 0.0

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
            f"Block validation: {validation_time:0.2f}s, "
            f"pre_validation: {pre_validation_time:0.2f}s, "
            f"CLVM: {pre_validation_result.timing / 1000.0:0.2f}s, "
            f"add-block: {add_block_time:0.2f}s, "
            f"post-process: {post_process_time:0.2f}s, "
            f"post-process2: {post_process_time2:0.2f}s, "
            f"cost: {block.transactions_info.cost if block.transactions_info is not None else 'None'}"
            f"{percent_full_str} header_hash: {header_hash.hex()} height: {block.height}",
        )

        # this is not covered by any unit tests as it's essentially test code
        # itself. It's exercised manually when investigating performance issues
        if validation_time > 2 and pr is not None:  # pragma: no cover
            pr.create_stats()
            profile_dir = path_from_root(self.root_path, "block-validation-profile")
            pr.dump_stats(profile_dir / f"{block.height}-{validation_time:0.1f}.profile")

        # This code path is reached if added == ADDED_AS_ORPHAN or NEW_TIP
        peak = self.blockchain.get_peak()
        assert peak is not None

        # Removes all temporary data for old blocks
        clear_height = uint32(max(0, peak.height - 50))
        self.full_node_store.clear_candidate_blocks_below(clear_height)
        self.full_node_store.clear_unfinished_blocks_below(clear_height)

        state_changed_data: dict[str, Any] = {
            "transaction_block": False,
            "k_size": block.reward_chain_block.proof_of_space.size().size_v1,
            "k_size2": block.reward_chain_block.proof_of_space.size().size_v2,
            "header_hash": block.header_hash,
            "fork_height": None,
            "rolled_back_records": None,
            "height": block.height,
            "validation_time": validation_time,
            "pre_validation_time": pre_validation_time,
        }

        if state_change_summary is not None:
            state_changed_data["fork_height"] = state_change_summary.fork_height
            state_changed_data["rolled_back_records"] = len(state_change_summary.rolled_back_records)

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
            self._segment_task_list.append(
                create_referenced_task(self.weight_proof_handler.create_prev_sub_epoch_segments())
            )
            for task in self._segment_task_list[:]:
                if task.done():
                    self._segment_task_list.remove(task)
        return None

    async def add_unfinished_block(
        self,
        block: UnfinishedBlock,
        peer: Optional[WSChiaConnection],
        farmed_block: bool = False,
    ) -> None:
        """
        We have received an unfinished block, either created by us, or from another peer.
        We can validate and add it and if it's a good block, propagate it to other peers and
        timelords.
        """
        receive_time = time.time()

        if (
            block.prev_header_hash != self.constants.GENESIS_CHALLENGE
            and self.blockchain.try_block_record(block.prev_header_hash) is None
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

        block_hash = bytes32(block.reward_chain_block.get_hash())
        foliage_tx_hash = block.foliage.foliage_transaction_block_hash

        # If we have already added the block with this reward block hash and
        # foliage hash, return
        if self.full_node_store.get_unfinished_block2(block_hash, foliage_tx_hash)[0] is not None:
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

        async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
            start_header_time = time.monotonic()
            _, header_error = await self.blockchain.validate_unfinished_block_header(block)
            if header_error is not None:
                if header_error == Err.TIMESTAMP_TOO_FAR_IN_FUTURE:
                    raise TimestampError
                else:
                    raise ConsensusError(header_error)
            validate_time = time.monotonic() - start_header_time
            self.log.log(
                logging.WARNING if validate_time > 2 else logging.DEBUG,
                f"Time for header validate: {validate_time:0.3f}s",
            )

        if block.transactions_generator is not None:
            pre_validation_start = time.monotonic()
            assert block.transactions_info is not None
            if len(block.transactions_generator_ref_list) > 0:
                generator_refs = set(block.transactions_generator_ref_list)
                generators: dict[uint32, bytes] = await self.blockchain.lookup_block_generators(
                    block.prev_header_hash, generator_refs
                )
                generator_args = [generators[height] for height in block.transactions_generator_ref_list]
            else:
                generator_args = []

            height = uint32(0) if prev_b is None else uint32(prev_b.height + 1)
            flags = get_flags_for_height_and_constants(height, self.constants)

            # on mainnet we won't receive unfinished blocks for heights
            # below the hard fork activation, but we have tests where we do
            if height >= self.constants.HARD_FORK_HEIGHT:
                run_block = run_block_generator2
            else:
                run_block = run_block_generator

            # run_block() also validates the signature
            err, conditions = await asyncio.get_running_loop().run_in_executor(
                self.blockchain.pool,
                run_block,
                bytes(block.transactions_generator),
                generator_args,
                min(self.constants.MAX_BLOCK_COST_CLVM, block.transactions_info.cost),
                flags,
                block.transactions_info.aggregated_signature,
                self._bls_cache,
                self.constants,
            )

            if err is not None:
                raise ConsensusError(Err(err))
            assert conditions is not None
            assert conditions.validated_signature
            npc_result = NPCResult(None, conditions)
            pre_validation_time = time.monotonic() - pre_validation_start

        async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.high):
            # TODO: pre-validate VDFs outside of lock
            validation_start = time.monotonic()
            validate_result = await self.blockchain.validate_unfinished_block(block, npc_result)
            if validate_result.error is not None:
                raise ConsensusError(Err(validate_result.error))
            validation_time = time.monotonic() - validation_start

        assert validate_result.required_iters is not None

        # Perform another check, in case we have already concurrently added the same unfinished block
        if self.full_node_store.get_unfinished_block2(block_hash, foliage_tx_hash)[0] is not None:
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
        block_duration_in_seconds = (
            receive_time - self.signage_point_times[block.reward_chain_block.signage_point_index]
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
                f"{block_duration_in_seconds:0.4f}, "
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

        # create two versions of the NewUnfinishedBlock message, one to be sent
        # to newer clients and one for older clients
        full_node_request = full_node_protocol.NewUnfinishedBlock(block.reward_chain_block.get_hash())
        msg = make_msg(ProtocolMessageTypes.new_unfinished_block, full_node_request)

        full_node_request2 = full_node_protocol.NewUnfinishedBlock2(
            block.reward_chain_block.get_hash(), block.foliage.foliage_transaction_block_hash
        )
        msg2 = make_msg(ProtocolMessageTypes.new_unfinished_block2, full_node_request2)

        def old_clients(conn: WSChiaConnection) -> bool:
            # don't send this to peers with new clients
            return conn.protocol_version <= Version("0.0.35")

        def new_clients(conn: WSChiaConnection) -> bool:
            # don't send this to peers with old clients
            return conn.protocol_version > Version("0.0.35")

        peer_id: Optional[bytes32] = None if peer is None else peer.peer_node_id
        await self.server.send_to_all_if([msg], NodeType.FULL_NODE, old_clients, peer_id)
        await self.server.send_to_all_if([msg2], NodeType.FULL_NODE, new_clients, peer_id)

        self._state_changed(
            "unfinished_block",
            {
                "block_duration_in_seconds": block_duration_in_seconds,
                "validation_time_in_seconds": validation_time,
                "pre_validation_time_in_seconds": pre_validation_time,
                "unfinished_block": block.to_json_dict(),
            },
        )

    async def new_infusion_point_vdf(
        self, request: timelord_protocol.NewInfusionPointVDF, timelord_peer: Optional[WSChiaConnection] = None
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
                self.log.warning(
                    f"Previous block is None, infusion point {request.reward_chain_ip_vdf.challenge.hex()}"
                )
                return None

        finished_sub_slots: Optional[list[EndOfSubSlotBundle]] = self.full_node_store.get_finished_sub_slots(
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
            await self.add_block(block, None, self._bls_cache, raise_on_disconnected=True)
        except Exception as e:
            self.log.warning(f"Consensus error validating block: {e}")
            if timelord_peer is not None:
                # Only sends to the timelord who sent us this VDF, to reset them to the correct peak
                await self.send_peak_to_timelords(peer=timelord_peer)
        return None

    async def add_end_of_sub_slot(
        self, end_of_slot_bundle: EndOfSubSlotBundle, peer: WSChiaConnection
    ) -> tuple[Optional[Message], bool]:
        fetched_ss = self.full_node_store.get_sub_slot(end_of_slot_bundle.challenge_chain.get_hash())

        # We are not interested in sub-slots which have the same challenge chain but different reward chain. If there
        # is a reorg, we will find out through the broadcast of blocks instead.
        if fetched_ss is not None:
            # Already have the sub-slot
            return None, True

        async with self.timelord_lock:
            fetched_ss = self.full_node_store.get_sub_slot(
                end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
            )
            if (
                (fetched_ss is None)
                and end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge
                != self.constants.GENESIS_CHALLENGE
            ):
                # If we don't have the prev, request the prev instead
                full_node_request = full_node_protocol.RequestSignagePointOrEndOfSubSlot(
                    end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                    uint8(0),
                    bytes32.zeros,
                )
                return (
                    make_msg(ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot, full_node_request),
                    False,
                )

            peak = self.blockchain.get_peak()
            if peak is not None and peak.height > 2:
                next_sub_slot_iters, next_difficulty = self.blockchain.get_next_sub_slot_iters_and_difficulty(
                    peak.header_hash, True
                )
            else:
                next_sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING
                next_difficulty = self.constants.DIFFICULTY_STARTING

            # Adds the sub slot and potentially get new infusions
            new_infusions = self.full_node_store.new_finished_sub_slot(
                end_of_slot_bundle,
                self.blockchain,
                peak,
                next_sub_slot_iters,
                next_difficulty,
                await self.blockchain.get_full_peak(),
            )
            # It may be an empty list, even if it's not None. Not None means added successfully
            if new_infusions is not None:
                self.log.info(
                    f"⏲️  Finished sub slot, SP {self.constants.NUM_SPS_SUB_SLOT}/{self.constants.NUM_SPS_SUB_SLOT}, "
                    f"{end_of_slot_bundle.challenge_chain.get_hash().hex()}, "
                    f"number of sub-slots: {len(self.full_node_store.finished_sub_slots)}, "
                    f"RC hash: {end_of_slot_bundle.reward_chain.get_hash().hex()}, "
                    f"Deficit {end_of_slot_bundle.reward_chain.deficit}"
                )
                # Reset farmer response timer for sub slot (SP 0)
                self.signage_point_times[0] = time.time()
                # Notify full nodes of the new sub-slot
                broadcast = full_node_protocol.NewSignagePointOrEndOfSubSlot(
                    end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
                    end_of_slot_bundle.challenge_chain.get_hash(),
                    uint8(0),
                    end_of_slot_bundle.reward_chain.end_of_slot_vdf.challenge,
                )
                msg = make_msg(ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot, broadcast)
                await self.server.send_to_all([msg], NodeType.FULL_NODE, peer.peer_node_id)

                for infusion in new_infusions:
                    await self.new_infusion_point_vdf(infusion)
                tx_peak = self.blockchain.get_tx_peak()
                # Notify farmers of the new sub-slot
                broadcast_farmer = farmer_protocol.NewSignagePoint(
                    end_of_slot_bundle.challenge_chain.get_hash(),
                    end_of_slot_bundle.challenge_chain.get_hash(),
                    end_of_slot_bundle.reward_chain.get_hash(),
                    next_difficulty,
                    next_sub_slot_iters,
                    uint8(0),
                    uint32(0) if peak is None else peak.height,
                    tx_peak.height if tx_peak is not None else uint32(0),
                    sp_source_data=SignagePointSourceData(
                        sub_slot_data=SPSubSlotSourceData(
                            end_of_slot_bundle.challenge_chain, end_of_slot_bundle.reward_chain
                        )
                    ),
                )
                msg = make_msg(ProtocolMessageTypes.new_signage_point, broadcast_farmer)
                await self.server.send_to_all([msg], NodeType.FARMER)
                return None, True
            else:
                self.log.info(
                    f"End of slot not added CC challenge "
                    f"{end_of_slot_bundle.challenge_chain.challenge_chain_end_of_slot_vdf.challenge.hex()}"
                )
        return None, False

    async def add_transaction(
        self, transaction: SpendBundle, spend_name: bytes32, peer: Optional[WSChiaConnection] = None, test: bool = False
    ) -> tuple[MempoolInclusionStatus, Optional[Err]]:
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
        # Ignore if syncing or if we have not yet received a block
        # the mempool must have a peak to validate transactions
        if self.sync_store.get_sync_mode() or self.mempool_manager.peak is None:
            status = MempoolInclusionStatus.FAILED
            error: Optional[Err] = Err.NO_TRANSACTIONS_WHILE_SYNCING
            self.mempool_manager.remove_seen(spend_name)
        else:
            try:
                cost_result = await self.mempool_manager.pre_validate_spendbundle(
                    transaction, spend_name, self._bls_cache
                )
            except ValidationError as e:
                self.mempool_manager.remove_seen(spend_name)
                return MempoolInclusionStatus.FAILED, e.code
            except Exception:
                self.mempool_manager.remove_seen(spend_name)
                raise

            if self.config.get("log_mempool", False):  # pragma: no cover
                try:
                    mempool_dir = path_from_root(self.root_path, "mempool-log") / f"{self.blockchain.get_peak_height()}"
                    mempool_dir.mkdir(parents=True, exist_ok=True)
                    with open(mempool_dir / f"{spend_name}.bundle", "wb+") as f:
                        f.write(bytes(transaction))
                except Exception:
                    self.log.exception(f"Failed to log mempool item: {spend_name}")

            async with self.blockchain.priority_mutex.acquire(priority=BlockchainMutexPriority.low):
                if self.mempool_manager.get_spendbundle(spend_name) is not None:
                    self.mempool_manager.remove_seen(spend_name)
                    return MempoolInclusionStatus.SUCCESS, None
                if self.mempool_manager.peak is None:
                    return MempoolInclusionStatus.FAILED, Err.MEMPOOL_NOT_INITIALIZED
                info = await self.mempool_manager.add_spend_bundle(
                    transaction, cost_result, spend_name, self.mempool_manager.peak.height
                )
                status = info.status
                error = info.error
            if status == MempoolInclusionStatus.SUCCESS:
                self.log.debug(
                    f"Added transaction to mempool: {spend_name} mempool size: "
                    f"{self.mempool_manager.mempool.total_mempool_cost()} normalized "
                    f"{self.mempool_manager.mempool.total_mempool_cost() / 5000000}"
                )

                # Only broadcast successful transactions, not pending ones. Otherwise it's a DOS
                # vector.
                mempool_item = self.mempool_manager.get_mempool_item(spend_name)
                assert mempool_item is not None
                await self.broadcast_removed_tx(info.removals)
                await self.broadcast_added_tx(mempool_item, current_peer=peer)

                if self.simulator_transaction_callback is not None:  # callback
                    await self.simulator_transaction_callback(spend_name)

            else:
                self.mempool_manager.remove_seen(spend_name)
                self.log.debug(f"Wasn't able to add transaction with id {spend_name}, status {status} error: {error}")
        return status, error

    async def broadcast_added_tx(
        self, mempool_item: MempoolItem, current_peer: Optional[WSChiaConnection] = None
    ) -> None:
        assert mempool_item.fee >= 0
        assert mempool_item.cost is not None

        new_tx = full_node_protocol.NewTransaction(
            mempool_item.name,
            mempool_item.cost,
            mempool_item.fee,
        )
        msg = make_msg(ProtocolMessageTypes.new_transaction, new_tx)
        if current_peer is None:
            await self.server.send_to_all([msg], NodeType.FULL_NODE)
        else:
            await self.server.send_to_all([msg], NodeType.FULL_NODE, current_peer.peer_node_id)

        conds = mempool_item.conds

        all_peers = {
            peer_id
            for peer_id, peer in self.server.all_connections.items()
            if peer.has_capability(Capability.MEMPOOL_UPDATES)
        }

        if len(all_peers) == 0:
            return

        start_time = time.monotonic()

        hints_for_removals = await self.hint_store.get_hints([bytes32(spend.coin_id) for spend in conds.spends])
        peer_ids = all_peers.intersection(peers_for_spend_bundle(self.subscriptions, conds, set(hints_for_removals)))

        for peer_id in peer_ids:
            peer = self.server.all_connections.get(peer_id)

            if peer is None:
                continue

            msg = make_msg(
                ProtocolMessageTypes.mempool_items_added, wallet_protocol.MempoolItemsAdded([mempool_item.name])
            )
            await peer.send_message(msg)

        total_time = time.monotonic() - start_time

        if len(peer_ids) == 0:
            self.log.log(
                logging.DEBUG if total_time < 0.5 else logging.WARNING,
                f"Looking up hints for {len(conds.spends)} spends took {total_time:.4f}s",
            )
        else:
            self.log.log(
                logging.DEBUG if total_time < 0.5 else logging.WARNING,
                f"Broadcasting added transaction {mempool_item.name} to {len(peer_ids)} peers took {total_time:.4f}s",
            )

    async def broadcast_removed_tx(self, mempool_removals: list[MempoolRemoveInfo]) -> None:
        total_removals = sum(len(r.items) for r in mempool_removals)
        if total_removals == 0:
            return

        start_time = time.monotonic()

        self.log.debug(f"Broadcasting {total_removals} removed transactions to peers")

        all_peers = {
            peer_id
            for peer_id, peer in self.server.all_connections.items()
            if peer.has_capability(Capability.MEMPOOL_UPDATES)
        }

        if len(all_peers) == 0:
            return

        removals_to_send: dict[bytes32, list[RemovedMempoolItem]] = dict()

        for removal_info in mempool_removals:
            for internal_mempool_item in removal_info.items:
                conds = internal_mempool_item.conds
                assert conds is not None

                hints_for_removals = await self.hint_store.get_hints([bytes32(spend.coin_id) for spend in conds.spends])
                peer_ids = all_peers.intersection(
                    peers_for_spend_bundle(self.subscriptions, conds, set(hints_for_removals))
                )

                if len(peer_ids) == 0:
                    continue

                transaction_id = internal_mempool_item.spend_bundle.name()

                self.log.debug(f"Broadcasting removed transaction {transaction_id} to wallet peers {peer_ids}")

                for peer_id in peer_ids:
                    peer = self.server.all_connections.get(peer_id)

                    if peer is None:
                        continue

                    removal = wallet_protocol.RemovedMempoolItem(transaction_id, uint8(removal_info.reason.value))
                    removals_to_send.setdefault(peer.peer_node_id, []).append(removal)

        for peer_id, removals in removals_to_send.items():
            peer = self.server.all_connections.get(peer_id)

            if peer is None:
                continue

            msg = make_msg(
                ProtocolMessageTypes.mempool_items_removed,
                wallet_protocol.MempoolItemsRemoved(removals),
            )
            await peer.send_message(msg)

        total_time = time.monotonic() - start_time

        self.log.log(
            logging.DEBUG if total_time < 0.5 else logging.WARNING,
            f"Broadcasting {total_removals} removed transactions "
            f"to {len(removals_to_send)} peers took {total_time:.4f}s",
        )

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
        if not validate_vdf(vdf_proof, self.constants, ClassgroupElement.get_default_element(), vdf_info):
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
                    new_proofs = sub_slot.proofs.replace(challenge_chain_slot_proof=vdf_proof)
                    new_subslot = sub_slot.replace(proofs=new_proofs)
                    new_finished_subslots = block.finished_sub_slots
                    new_finished_subslots[index] = new_subslot
                    new_block = block.replace(finished_sub_slots=new_finished_subslots)
                    break
        if field_vdf == CompressibleVDFField.ICC_EOS_VDF:
            for index, sub_slot in enumerate(block.finished_sub_slots):
                if (
                    sub_slot.infused_challenge_chain is not None
                    and sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf == vdf_info
                ):
                    new_proofs = sub_slot.proofs.replace(infused_challenge_chain_slot_proof=vdf_proof)
                    new_subslot = sub_slot.replace(proofs=new_proofs)
                    new_finished_subslots = block.finished_sub_slots
                    new_finished_subslots[index] = new_subslot
                    new_block = block.replace(finished_sub_slots=new_finished_subslots)
                    break
        if field_vdf == CompressibleVDFField.CC_SP_VDF:
            if block.reward_chain_block.challenge_chain_sp_vdf == vdf_info:
                assert block.challenge_chain_sp_proof is not None
                new_block = block.replace(challenge_chain_sp_proof=vdf_proof)
        if field_vdf == CompressibleVDFField.CC_IP_VDF:
            if block.reward_chain_block.challenge_chain_ip_vdf == vdf_info:
                new_block = block.replace(challenge_chain_ip_proof=vdf_proof)
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

    async def add_compact_proof_of_time(self, request: timelord_protocol.RespondCompactProofOfTime) -> None:
        peak = self.blockchain.get_peak()
        if peak is None or peak.height - request.height < 5:
            self.log.info(f"Ignoring add_compact_proof_of_time, height {request.height} too recent.")
            return None

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

    async def new_compact_vdf(self, request: full_node_protocol.NewCompactVDF, peer: WSChiaConnection) -> None:
        peak = self.blockchain.get_peak()
        if peak is None or peak.height - request.height < 5:
            self.log.info(f"Ignoring new_compact_vdf, height {request.height} too recent.")
            return None
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
            response = await peer.call_api(FullNodeAPI.request_compact_vdf, peer_request, timeout=10)
            if response is not None and isinstance(response, full_node_protocol.RespondCompactVDF):
                await self.add_compact_vdf(response, peer)

    async def request_compact_vdf(self, request: full_node_protocol.RequestCompactVDF, peer: WSChiaConnection) -> None:
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

    async def add_compact_vdf(self, request: full_node_protocol.RespondCompactVDF, peer: WSChiaConnection) -> None:
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
            await self.server.send_to_all([msg], NodeType.FULL_NODE, peer.peer_node_id)

    def in_bad_peak_cache(self, wp: WeightProof) -> bool:
        for block in wp.recent_chain_data:
            if block.header_hash in self.bad_peak_cache.keys():
                return True
        return False

    def add_to_bad_peak_cache(self, peak_header_hash: bytes32, peak_height: uint32) -> None:
        curr_height = self.blockchain.get_peak_height()

        if curr_height is None:
            self.log.debug(f"add bad peak {peak_header_hash} to cache")
            self.bad_peak_cache[peak_header_hash] = peak_height
            return
        minimum_cache_height = curr_height - (2 * self.constants.SUB_EPOCH_BLOCKS)
        if peak_height < minimum_cache_height:
            return

        new_cache = {}
        self.log.info(f"add bad peak {peak_header_hash} to cache")
        new_cache[peak_header_hash] = peak_height
        min_height = peak_height
        min_block = peak_header_hash
        for header_hash, height in self.bad_peak_cache.items():
            if height < minimum_cache_height:
                self.log.debug(f"remove bad peak {peak_header_hash} from cache")
                continue
            if height < min_height:
                min_block = header_hash
            new_cache[header_hash] = height

        if len(new_cache) > self.config.get("bad_peak_cache_size", 100):
            del new_cache[min_block]

        self.bad_peak_cache = new_cache

    async def broadcast_uncompact_blocks(
        self, uncompact_interval_scan: int, target_uncompact_proofs: int, sanitize_weight_proof_only: bool
    ) -> None:
        try:
            while not self._shut_down:
                while self.sync_store.get_sync_mode() or self.sync_store.get_long_sync():
                    if self._shut_down:
                        return None
                    await asyncio.sleep(30)

                broadcast_list: list[timelord_protocol.RequestCompactProofOfTime] = []

                self.log.info("Getting random heights for bluebox to compact")

                if self._server is None:
                    self.log.info("Not broadcasting uncompact blocks, no server found")
                    await asyncio.sleep(uncompact_interval_scan)
                    continue
                connected_timelords = self.server.get_connections(NodeType.TIMELORD)

                total_target_uncompact_proofs = target_uncompact_proofs * max(1, len(connected_timelords))
                heights = await self.block_store.get_random_not_compactified(total_target_uncompact_proofs)
                self.log.info("Heights found for bluebox to compact: [%s]", ", ".join(map(str, heights)))

                for h in heights:
                    headers = await self.blockchain.get_header_blocks_in_range(h, h, tx_filter=False)
                    records: dict[bytes32, BlockRecord] = {}
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

                broadcast_list_chunks: list[list[timelord_protocol.RequestCompactProofOfTime]] = []
                for index in range(0, len(broadcast_list), target_uncompact_proofs):
                    broadcast_list_chunks.append(broadcast_list[index : index + target_uncompact_proofs])
                if len(broadcast_list_chunks) == 0:
                    self.log.info("Did not find any uncompact blocks.")
                    await asyncio.sleep(uncompact_interval_scan)
                    continue
                if self.sync_store.get_sync_mode() or self.sync_store.get_long_sync():
                    await asyncio.sleep(uncompact_interval_scan)
                    continue
                if self._server is not None:
                    self.log.info(f"Broadcasting {len(broadcast_list)} items to the bluebox")
                    connected_timelords = self.server.get_connections(NodeType.TIMELORD)
                    chunk_index = 0
                    for connection in connected_timelords:
                        peer_node_id = connection.peer_node_id
                        msgs = []
                        broadcast_list = broadcast_list_chunks[chunk_index]
                        chunk_index = (chunk_index + 1) % len(broadcast_list_chunks)
                        for new_pot in broadcast_list:
                            msg = make_msg(ProtocolMessageTypes.request_compact_proof_of_time, new_pot)
                            msgs.append(msg)
                        await self.server.send_to_specific(msgs, peer_node_id)
                await asyncio.sleep(uncompact_interval_scan)
        except Exception as e:
            error_stack = traceback.format_exc()
            self.log.error(f"Exception in broadcast_uncompact_blocks: {e}")
            self.log.error(f"Exception Stack: {error_stack}")


async def node_next_block_check(
    peer: WSChiaConnection, potential_peek: uint32, blockchain: BlockchainInterface
) -> bool:
    block_response: Optional[Any] = await peer.call_api(
        FullNodeAPI.request_block, full_node_protocol.RequestBlock(potential_peek, True)
    )
    if block_response is not None and isinstance(block_response, full_node_protocol.RespondBlock):
        peak = blockchain.get_peak()
        if peak is not None and block_response.block.prev_header_hash == peak.header_hash:
            return True
    return False
