import logging
from pathlib import Path
from typing import Any, Dict

import aiosqlite

from chia.consensus.constants import ConsensusConstants
from chia.data_layer.data_store import DataStore
from chia.util.db_wrapper import DBWrapper
from chia.util.path import mkdir, path_from_root


class DataLayer:
    data_store: DataStore
    db_wrapper: DBWrapper
    db_path: Path
    # block_store: BlockStore
    # full_node_store: FullNodeStore
    # full_node_peers: Optional[FullNodePeers]
    # sync_store: Any
    # coin_store: CoinStore
    # mempool_manager: MempoolManager
    connection: aiosqlite.Connection
    # _sync_task: Optional[asyncio.Task]
    # _init_weight_proof: Optional[asyncio.Task] = None
    # blockchain: Blockchain
    # config: Dict
    server: Any
    log: logging.Logger
    # constants: ConsensusConstants
    # _shut_down: bool
    # root_path: Path
    # state_changed_callback: Optional[Callable]
    # timelord_lock: asyncio.Lock
    initialized: bool
    # weight_proof_handler: Optional[WeightProofHandler]
    # _ui_tasks: Set[asyncio.Task]

    def __init__(
        self,
        config: Dict,
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: str = None,
    ):
        self.initialized = False
        # self.root_path = root_path
        # self.config = config
        self.server = None
        # self._shut_down = False  # Set to true to close all infinite loops
        # self.constants = consensus_constants
        # self.pow_creation: Dict[uint32, asyncio.Event] = {}
        # self.state_changed_callback: Optional[Callable] = None
        # self.full_node_peers = None
        # self.sync_store = None
        # self.signage_point_times = [time.time() for _ in range(self.constants.NUM_SPS_SUB_SLOT)]
        # self.full_node_store = FullNodeStore(self.constants)
        # self.uncompact_task = None
        # self.compact_vdf_requests: Set[bytes32] = set()
        self.log = logging.getLogger(name if name else __name__)

        # self._ui_tasks = set()

        # TODO: use the data layer database
        db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
        self.db_path = path_from_root(root_path, db_path_replaced)
        mkdir(self.db_path.parent)

    # def _set_state_changed_callback(self, callback: Callable):
    #     self.state_changed_callback = callback

    async def _start(self):
        # self.timelord_lock = asyncio.Lock()
        # self.compact_vdf_sem = asyncio.Semaphore(4)
        # self.new_peak_sem = asyncio.Semaphore(8)
        # # create the store (db) and full node instance
        self.connection = await aiosqlite.connect(self.db_path)
        # if self.config.get("log_sqlite_cmds", False):
        #     sql_log_path = path_from_root(self.root_path, "log/sql.log")
        #     self.log.info(f"logging SQL commands to {sql_log_path}")
        #
        #     def sql_trace_callback(req: str):
        #         timestamp = datetime.now().strftime("%H:%M:%S.%f")
        #         log = open(sql_log_path, "a")
        #         log.write(timestamp + " " + req + "\n")
        #         log.close()
        #
        #     await self.connection.set_trace_callback(sql_trace_callback)
        self.db_wrapper = DBWrapper(self.connection)
        self.data_store = await DataStore.create(self.db_wrapper)

        # self.sync_store = await SyncStore.create()
        # self.coin_store = await CoinStore.create(self.db_wrapper)
        # self.log.info("Initializing blockchain from disk")
        # start_time = time.time()
        # self.blockchain = await Blockchain.create(self.coin_store, self.block_store, self.constants)
        # self.mempool_manager = MempoolManager(self.coin_store, self.constants)
        # self.weight_proof_handler = None
        # self._init_weight_proof = asyncio.create_task(self.initialize_weight_proof())
        #
        # if self.config.get("enable_profiler", False):
        #     asyncio.create_task(profile_task(self.root_path, "node", self.log))
        #
        # self._sync_task = None
        # self._segment_task = None
        # time_taken = time.time() - start_time
        # if self.blockchain.get_peak() is None:
        #     self.log.info(f"Initialized with empty blockchain time taken: {int(time_taken)}s")
        # else:
        #     self.log.info(
        #         f"Blockchain initialized to peak {self.blockchain.get_peak().header_hash} height"
        #         f" {self.blockchain.get_peak().height}, "
        #         f"time taken: {int(time_taken)}s"
        #     )
        #     pending_tx = await self.mempool_manager.new_peak(self.blockchain.get_peak())
        #     assert len(pending_tx) == 0  # no pending transactions when starting up
        #
        # peak: Optional[BlockRecord] = self.blockchain.get_peak()
        # if peak is not None:
        #     full_peak = await self.blockchain.get_full_peak()
        #     await self.peak_post_processing(full_peak, peak, max(peak.height - 1, 0), None)
        # if self.config["send_uncompact_interval"] != 0:
        #     sanitize_weight_proof_only = False
        #     if "sanitize_weight_proof_only" in self.config:
        #         sanitize_weight_proof_only = self.config["sanitize_weight_proof_only"]
        #     assert self.config["target_uncompact_proofs"] != 0
        #     self.uncompact_task = asyncio.create_task(
        #         self.broadcast_uncompact_blocks(
        #             self.config["send_uncompact_interval"],
        #             self.config["target_uncompact_proofs"],
        #             sanitize_weight_proof_only,
        #         )
        #     )
        # self.initialized = True
        # if self.full_node_peers is not None:
        #     asyncio.create_task(self.full_node_peers.start())

    # def _state_changed(self, change: str):
    #     if self.state_changed_callback is not None:
    #         self.state_changed_callback(change)

    # async def _refresh_ui_connections(self, sleep_before: float = 0):
    #     if sleep_before > 0:
    #         await asyncio.sleep(sleep_before)
    #     self._state_changed("peer_changed_peak")
