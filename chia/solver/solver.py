from __future__ import annotations

import asyncio
import concurrent
import contextlib
import logging
from collections.abc import AsyncIterator
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Optional, cast

from chia_rs import ConsensusConstants

from chia.protocols.outbound_message import NodeType
from chia.protocols.solver_protocol import SolverInfo
from chia.rpc.rpc_server import StateChangedProtocol, default_get_connections
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection

log = logging.getLogger(__name__)


class Solver:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcServiceProtocol

        _protocol_check: ClassVar[RpcServiceProtocol] = cast("Solver", None)

    root_path: Path
    _server: Optional[ChiaServer]
    _shut_down: bool
    started: bool = False
    executor: ThreadPoolExecutor
    state_changed_callback: Optional[StateChangedProtocol] = None
    constants: ConsensusConstants
    event_loop: asyncio.events.AbstractEventLoop

    @property
    def server(self) -> ChiaServer:
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    def __init__(self, root_path: Path, config: dict[str, Any], constants: ConsensusConstants):
        self.log = log
        self.root_path = root_path
        self._shut_down = False
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=config["num_threads"], thread_name_prefix="solver-"
        )
        self._server = None
        self.constants = constants
        self.state_changed_callback: Optional[StateChangedProtocol] = None

    @contextlib.asynccontextmanager
    async def manage(self) -> AsyncIterator[None]:
        try:
            self.started = True
            yield
        finally:
            self._shut_down = True

    def solve(self, info: SolverInfo) -> Optional[bytes]:
        self.log.debug(f"Solve called with SolverInfo: {info}")
        return None

    def get_connections(self, request_node_type: Optional[NodeType]) -> list[dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    async def on_connect(self, connection: WSChiaConnection) -> None:
        pass

    async def on_disconnect(self, connection: WSChiaConnection) -> None:
        self.log.info(f"peer disconnected {connection.get_peer_logging()}")

    def set_server(self, server: ChiaServer) -> None:
        self._server = server

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        self.state_changed_callback = callback
