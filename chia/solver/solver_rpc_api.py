from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Optional, cast

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64

from chia.protocols.solver_protocol import SolverInfo
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
            "/solve": self.solve,
            "/get_state": self.get_state,
        }

    async def _state_changed(self, change: str, change_data: Optional[dict[str, Any]] = None) -> list[WsRpcMessage]:
        return []

    async def solve(self, request: dict[str, Any]) -> EndpointResult:
        # extract all required fields from request
        quality_string = request["quality_string"]
        plot_size = request.get("plot_size", 32)  # todo default ?
        plot_difficulty = request.get("plot_difficulty", 1000)  # todo default ?

        # create complete SolverInfo object with all provided data
        solver_info = SolverInfo(
            plot_size=uint8(plot_size),
            plot_difficulty=uint64(plot_difficulty),
            quality_string=bytes32.from_hexstr(quality_string),
        )

        proof = self.service.solve(solver_info)
        return {"proof": proof.hex() if proof else None}

    async def get_state(self, _: dict[str, Any]) -> EndpointResult:
        return {
            "started": self.service.started,
        }
