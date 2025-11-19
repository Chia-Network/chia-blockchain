from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from chia.rpc.rpc_server import Endpoint, EndpointResult
from chia.solver.solver import Solver
from chia.util.ws_message import WsRpcMessage


class SolverRpcApi:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcApiProtocol

        _protocol_check: ClassVar[RpcApiProtocol] = cast("SolverRpcApi", None)

    def __init__(self, solver: Solver):
        self.service = solver
        self.service_name = "chia_solver"

    def get_routes(self) -> dict[str, Endpoint]:
        return {
            "/get_state": self.get_state,
        }

    async def _state_changed(self, change: str, change_data: dict[str, Any] | None = None) -> list[WsRpcMessage]:
        return []

    async def get_state(self, _: dict[str, Any]) -> EndpointResult:
        return {
            "started": self.service.started,
        }
