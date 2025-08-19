from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Optional, cast

from chia_rs.sized_ints import uint64

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
        partial_proof = request["partial_proof"]
        plot_difficulty = request.get("plot_difficulty", 1000)  # todo default ?

        # create complete SolverInfo object with all provided data
        solver_info = SolverInfo(
            plot_difficulty=uint64(plot_difficulty),
            partial_proof=bytes.fromhex(partial_proof),
        )

        proof = self.service.solve(solver_info)
        return {"proof": proof.hex() if proof else None}

    async def get_state(self, _: dict[str, Any]) -> EndpointResult:
        return {
            "started": self.service.started,
        }
