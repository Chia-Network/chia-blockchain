import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import aiosqlite

from chia.consensus.constants import ConsensusConstants
from chia.data_layer.data_store import DataStore
from chia.server.server import ChiaServer
from chia.util.db_wrapper import DBWrapper
from chia.util.path import mkdir, path_from_root


class DataLayer:
    data_store: DataStore
    db_wrapper: DBWrapper
    db_path: Path
    connection: aiosqlite.Connection
    config: Dict
    server: Any
    log: logging.Logger
    # constants: ConsensusConstants
    # _shut_down: bool
    # root_path: Path
    state_changed_callback: Optional[Callable]
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
        # self.root_path = root_path
        self.config = config
        self.server = None
        # self.constants = consensus_constants
        self.state_changed_callback: Optional[Callable] = None
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

    # def _state_changed(self, change: str):
    #     if self.state_changed_callback is not None:
    #         self.state_changed_callback(change)

    # async def _refresh_ui_connections(self, sleep_before: float = 0):
    #     if sleep_before > 0:
    #         await asyncio.sleep(sleep_before)
    #     self._state_changed("peer_changed_peak")
