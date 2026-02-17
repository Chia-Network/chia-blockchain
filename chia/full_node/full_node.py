from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import multiprocessing
import sqlite3
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from multiprocessing.context import BaseContext
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, TextIO, cast, final

from chia_rs import (
    BlockRecord,
    BLSCache,
    ConsensusConstants,
    FullBlock,
    SubEpochSummary,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia.consensus.block_height_map import BlockHeightMap
from chia.consensus.blockchain import Blockchain, BlockchainMutexPriority, StateChangeSummary
from chia.consensus.coin_store_protocol import CoinStoreProtocol
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.full_node_store import FullNodeStore
from chia.full_node.hint_store import HintStore
from chia.full_node.mempool_manager import MempoolManager
from chia.full_node.subscriptions import PeerSubscriptions
from chia.full_node.sync_store import Peak, SyncStore
from chia.full_node.tx_processing_queue import TransactionQueue, TransactionQueueEntry
from chia.full_node.weight_proof import WeightProofHandler
from chia.protocols import full_node_protocol, timelord_protocol, wallet_protocol
from chia.protocols.outbound_message import NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.protocol_timing import CONSENSUS_ERROR_BAN_SECONDS
from chia.rpc.rpc_server import StateChangedProtocol
from chia.server.node_discovery import FullNodePeers
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.config import process_config_start_method
from chia.util.db_synchronous import db_synchronous_on
from chia.util.db_version import lookup_db_version, set_db_version_async
from chia.util.db_wrapper import DBWrapper2, manage_connection
from chia.util.errors import Err, ValidationError
from chia.util.limited_semaphore import LimitedSemaphore
from chia.util.path import path_from_root
from chia.util.profiler import mem_profile_task, profile_task
from chia.util.safe_cancel_task import cancel_task_safe
from chia.util.task_referencer import create_referenced_task

# Import extracted modules
from chia.full_node import full_node_block_processing as _fn_blocks
from chia.full_node import full_node_compact_vdf as _fn_compact_vdf
from chia.full_node import full_node_sync as _fn_sync
from chia.full_node import full_node_transactions as _fn_tx

# Re-export these for backward compatibility (they were originally defined here)
from chia.full_node.full_node_block_processing import PeakPostProcessingResult as PeakPostProcessingResult  # noqa: F401
from chia.full_node.full_node_block_processing import WalletUpdate as WalletUpdate  # noqa: F401
from chia.full_node.full_node_sync import node_next_block_check as node_next_block_check  # noqa: F401


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
    _server: ChiaServer | None = None
    _shut_down: bool = False
    pow_creation: dict[bytes32, asyncio.Event] = dataclasses.field(default_factory=dict)
    state_changed_callback: StateChangedProtocol | None = None
    full_node_peers: FullNodePeers | None = None
    sync_store: SyncStore = dataclasses.field(default_factory=SyncStore)
    uncompact_task: asyncio.Task[None] | None = None
    compact_vdf_requests: set[bytes32] = dataclasses.field(default_factory=set)
    # TODO: Logging isn't setup yet so the log entries related to parsing the
    #       config would end up on stdout if handled here.
    multiprocessing_context: BaseContext | None = None
    _ui_tasks: set[asyncio.Task[None]] = dataclasses.field(default_factory=set)
    subscriptions: PeerSubscriptions = dataclasses.field(default_factory=PeerSubscriptions)
    _transaction_queue_task: asyncio.Task[None] | None = None
    simulator_transaction_callback: Callable[[bytes32], Awaitable[None]] | None = None
    _sync_task_list: list[asyncio.Task[None]] = dataclasses.field(default_factory=list)
    _transaction_queue: TransactionQueue | None = None
    _tx_task_list: list[asyncio.Task[None]] = dataclasses.field(default_factory=list)
    _compact_vdf_sem: LimitedSemaphore | None = None
    _new_peak_sem: LimitedSemaphore | None = None
    _add_transaction_semaphore: asyncio.Semaphore | None = None
    _db_wrapper: DBWrapper2 | None = None
    _hint_store: HintStore | None = None
    _block_store: BlockStore | None = None
    _coin_store: CoinStoreProtocol | None = None
    _mempool_manager: MempoolManager | None = None
    _init_weight_proof: asyncio.Task[None] | None = None
    _blockchain: Blockchain | None = None
    _timelord_lock: asyncio.Lock | None = None
    weight_proof_handler: WeightProofHandler | None = None
    # hashes of peaks that failed long sync on chip13 Validation
    bad_peak_cache: dict[bytes32, uint32] = dataclasses.field(default_factory=dict)
    wallet_sync_task: asyncio.Task[None] | None = None
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

        sql_log_path: Path | None = None
        with contextlib.ExitStack() as exit_stack:
            sql_log_file: TextIO | None = None
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

            async with MempoolManager.managed(
                get_coin_records=self.coin_store.get_coin_records,
                get_unspent_lineage_info_for_puzzle_hash=self.coin_store.get_unspent_lineage_info_for_puzzle_hash,
                consensus_constants=self.constants,
                single_threaded=single_threaded,
            ) as self._mempool_manager:
                # Transactions go into this queue from the server, and get sent to respond_transaction
                self._transaction_queue = TransactionQueue(
                    1000, self.log, max_tx_clvm_cost=uint64(self.constants.MAX_BLOCK_COST_CLVM // 2)
                )
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
                peak: BlockRecord | None = self.blockchain.get_peak()
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
                        # No pending transactions when starting up
                        assert len(pending_tx.spend_bundle_ids) == 0

                        full_peak: FullBlock | None = await self.blockchain.get_full_peak()
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

    def get_connections(self, request_node_type: NodeType | None) -> list[dict[str, Any]]:
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
            inc_status, err = await self.add_transaction(
                entry.transaction, entry.spend_name, peer, entry.test, entry.peers_with_tx
            )
            entry.done.set((inc_status, err))
        except asyncio.CancelledError:
            error_stack = traceback.format_exc()
            self.log.debug(f"Cancelling _handle_one_transaction, closing: {error_stack}")
        except ValidationError as e:
            self.log.exception("ValidationError in _handle_one_transaction, closing")
            if peer is not None:
                await peer.close(CONSENSUS_ERROR_BAN_SECONDS)
            entry.done.set((MempoolInclusionStatus.FAILED, e.code))
        except Exception:
            self.log.exception("Error in _handle_one_transaction, closing")
            if peer is not None:
                await peer.close(CONSENSUS_ERROR_BAN_SECONDS)
            entry.done.set((MempoolInclusionStatus.FAILED, Err.UNKNOWN))
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

    def _state_changed(self, change: str, change_data: dict[str, Any] | None = None) -> None:
        if self.state_changed_callback is not None:
            self.state_changed_callback(change, change_data)

    async def send_peak_to_timelords(
        self, peak_block: FullBlock | None = None, peer: WSChiaConnection | None = None
    ) -> None:
        """
        Sends current peak to timelords
        """
        if peak_block is None:
            peak_block = await self.blockchain.get_full_peak()
        if peak_block is not None:
            peak = self.blockchain.block_record(peak_block.header_hash)
            difficulty = self.blockchain.get_next_sub_slot_iters_and_difficulty(peak.header_hash, False)[1]
            ses: SubEpochSummary | None = next_sub_epoch_summary(
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

    async def synced(self, block_is_current_at: uint64 | None = None) -> bool:
        if block_is_current_at is None:
            block_is_current_at = uint64(time.time() - 60 * 7)
        if "simulator" in str(self.config.get("selected_network")):
            return True  # sim is always synced because it has no peers
        curr: BlockRecord | None = self.blockchain.get_peak()
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

        peak_full: FullBlock | None = await self.blockchain.get_full_peak()

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
        changes_for_peer: dict[bytes32, set] = {}
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
                state = wallet_protocol.CoinStateUpdate(
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

    # ===== Methods from full_node_sync.py =====
    short_sync_batch = _fn_sync.short_sync_batch
    short_sync_backtrack = _fn_sync.short_sync_backtrack
    _refresh_ui_connections = _fn_sync._refresh_ui_connections
    new_peak = _fn_sync.new_peak
    _sync = _fn_sync._sync
    request_validate_wp = _fn_sync.request_validate_wp
    sync_from_fork_point = _fn_sync.sync_from_fork_point
    get_peers_with_peak = _fn_sync.get_peers_with_peak
    _finish_sync = _fn_sync._finish_sync

    # ===== Methods from full_node_block_processing.py =====
    add_block_batch = _fn_blocks.add_block_batch
    skip_blocks = _fn_blocks.skip_blocks
    prevalidate_blocks = _fn_blocks.prevalidate_blocks
    add_prevalidated_blocks = _fn_blocks.add_prevalidated_blocks
    get_sub_slot_iters_difficulty_ses_block = _fn_blocks.get_sub_slot_iters_difficulty_ses_block
    has_valid_pool_sig = _fn_blocks.has_valid_pool_sig
    signage_point_post_processing = _fn_blocks.signage_point_post_processing
    peak_post_processing = _fn_blocks.peak_post_processing
    peak_post_processing_2 = _fn_blocks.peak_post_processing_2
    add_block = _fn_blocks.add_block
    add_unfinished_block = _fn_blocks.add_unfinished_block
    new_infusion_point_vdf = _fn_blocks.new_infusion_point_vdf
    add_end_of_sub_slot = _fn_blocks.add_end_of_sub_slot

    # ===== Methods from full_node_transactions.py =====
    add_transaction = _fn_tx.add_transaction
    broadcast_added_tx = _fn_tx.broadcast_added_tx
    broadcast_removed_tx = _fn_tx.broadcast_removed_tx

    # ===== Methods from full_node_compact_vdf.py =====
    _needs_compact_proof = _fn_compact_vdf._needs_compact_proof
    _can_accept_compact_proof = _fn_compact_vdf._can_accept_compact_proof
    _replace_proof = _fn_compact_vdf._replace_proof
    add_compact_proof_of_time = _fn_compact_vdf.add_compact_proof_of_time
    new_compact_vdf = _fn_compact_vdf.new_compact_vdf
    request_compact_vdf = _fn_compact_vdf.request_compact_vdf
    add_compact_vdf = _fn_compact_vdf.add_compact_vdf
    in_bad_peak_cache = _fn_compact_vdf.in_bad_peak_cache
    add_to_bad_peak_cache = _fn_compact_vdf.add_to_bad_peak_cache
    broadcast_uncompact_blocks = _fn_compact_vdf.broadcast_uncompact_blocks
