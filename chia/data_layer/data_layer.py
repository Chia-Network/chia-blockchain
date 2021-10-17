import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiosqlite

from chia.consensus.constants import ConsensusConstants
from chia.data_layer.data_layer_types import Side
from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.data_layer.data_store import DataStore
from chia.server.server import ChiaServer
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper
from chia.util.path import mkdir, path_from_root


class DataLayer:
    data_store: DataStore
    db_wrapper: DBWrapper
    db_path: Path
    connection: aiosqlite.Connection
    config: Dict[str, Any]
    server: Any
    log: logging.Logger
    wallet: DataLayerWallet
    # _shut_down: bool
    # root_path: Path
    state_changed_callback: Optional[Callable[..., object]]
    initialized: bool
    # _ui_tasks: Set[asyncio.Task]

    def __init__(
        self,
        # TODO: Is this at least `Dict[str, Any]`?
        config: Dict[Any, Any],
        root_path: Path,
        consensus_constants: ConsensusConstants,
        name: Optional[str] = None,
    ):
        if name == "":
            # TODO: If no code depends on "" counting as 'unspecified' then we do not
            #       need this.
            name = None

        self.initialized = False
        self.wallet = DataLayerWallet()
        self.config = config
        self.server = None
        # self.constants = consensus_constants
        self.state_changed_callback = None
        self.log = logging.getLogger(name if name is None else __name__)

        # self._ui_tasks = set()

        # TODO: use the data layer database
        db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
        self.db_path = path_from_root(root_path, db_path_replaced)
        mkdir(self.db_path.parent)

    def _set_state_changed_callback(self, callback: Callable[..., object]) -> None:
        self.state_changed_callback = callback

    def set_server(self, server: ChiaServer) -> None:
        self.server = server

    async def _start(self) -> None:
        # create the store (db) and data store instance
        self.connection = await aiosqlite.connect(self.db_path)
        self.db_wrapper = DBWrapper(self.connection)
        self.data_store = await DataStore.create(self.db_wrapper)

        self.initialized = True

    def _close(self) -> None:
        # TODO: review for anything else we need to do here
        # self._shut_down = True
        pass

    async def _await_closed(self) -> None:
        await self.connection.close()

    async def create_store(self) -> bytes32:
        # todo  create singelton with wavaluellet and get id
        store_id = await self.wallet.create_data_store()
        res = await self.data_store.create_tree(store_id)
        if res is False:
            self.log.error("Failed to create tree")
        return store_id

    async def insert(
        self,
        tree_id: bytes32,
        changelist: List[Dict[str, Any]],
    ) -> bool:
        for change in changelist:
            if change["action"] == "insert":
                key = Program.from_bytes(bytes(change["key"]))
                value = Program.from_bytes(bytes(change["value"]))
                reference_node_hash = None
                if "reference_node_hash" in change:
                    reference_node_hash = Program.from_bytes(change["reference_node_hash"])
                side = None
                if side in change:
                    side = Side(change["side"])
                await self.data_store.insert(key, value, tree_id, reference_node_hash, side)
            else:
                assert change["action"] == "delete"
                key = Program.from_bytes(change["key"])
                await self.data_store.delete(key, tree_id)

        # state = await self.data_store.get_table_state(table)
        # await self.data_layer_wallet.uptate_table_state(table, state, std_hash(action_list))
        # todo need to mark data as pending and change once tx is confirmed
        return True

    async def get_value(self) -> bytes32:
        # todo  create singelton with wallet and get id
        id = "0102030405060708091011121314151617181920212223242526272829303132"
        res = await self.data_store.create_tree(id)
        if res is False:
            self.log.error("Failed to create tree")
        return id

    # def _state_changed(self, change: str):
    #     if self.state_changed_callback is not None:
    #         self.state_changed_callback(change)

    # async def _refresh_ui_connections(self, sleep_before: float = 0):
    #     if sleep_before > 0:
    #         await asyncio.sleep(sleep_before)
    #     self._state_changed("peer_changed_peak")
