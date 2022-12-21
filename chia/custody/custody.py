from __future__ import annotations

import asyncio
import logging
import random
import time
import traceback
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

import aiohttp

from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.util.path import path_from_root



class Custody:
    config: Dict[str, Any]
    log: logging.Logger
    wallet_rpc_init: Awaitable[WalletRpcClient]
    state_changed_callback: Optional[Callable[..., object]]
    wallet_id: uint64
    initialized: bool
    none_bytes: bytes32
    lock: asyncio.Lock
    _server: Optional[ChiaServer]

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
        name: Optional[str] = None,
    ):
        if name == "":
            # TODO: If no code depends on "" counting as 'unspecified' then we do not
            #       need this.
            name = None
        self.initialized = False
        self.config = config
        self.connection = None
        self.log = logging.getLogger(name if name is None else __name__)
        self._shut_down: bool = False
        db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
        self.db_path = path_from_root(root_path, db_path_replaced)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        server_files_replaced: str = config.get(
            "server_files_location", "data_layer/db/server_files_location_CHALLENGE"
        ).replace("CHALLENGE", config["selected_network"])
        self.server_files_location = path_from_root(root_path, server_files_replaced)
        self.server_files_location.mkdir(parents=True, exist_ok=True)
        self.none_bytes = bytes32([0] * 32)
        self.lock = asyncio.Lock()
        self._server = None

    def _set_state_changed_callback(self, callback: Callable[..., object]) -> None:
        self.state_changed_callback = callback

    async def on_connect(self, connection: WSChiaConnection) -> None:
        pass

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    def set_server(self, server: ChiaServer) -> None:
        self._server = server

    async def _start(self) -> None:
        self.subscription_lock: asyncio.Lock = asyncio.Lock()

    def _close(self) -> None:
        # TODO: review for anything else we need to do here
        self._shut_down = True

    async def _await_closed(self) -> None:
        if self.connection is not None:
            await self.connection.close()
      
    async def init_cmd(
        self,
        directory: str,
        withdrawal_timelock: int,
        payment_clawback: int,
        rekey_cancel: int,
        rekey_timelock: int,
        slow_penalty: int,
    ) -> None:
        from chia.custody.cic.cli.main import init_cmd

        await init_cmd(directory, withdrawal_timelock, payment_clawback, rekey_cancel, rekey_timelock, slow_penalty)


    async def derive_cmd(
        self,
        custody_rpc_port: Optional[int],
        configuration: str,
        db_path: str,
        pubkeys: str,
        initial_lock_level: int,
        minimum_pks: int,
        validate_against: str,
        maximum_lock_level: int,
    ):
        from chia.custody.cic.cli.main import derive_cmd

        await derive_cmd(configuration, db_path, pubkeys, initial_lock_level, minimum_pks, validate_against, maximum_lock_level)

