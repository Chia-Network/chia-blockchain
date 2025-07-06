from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Optional, cast

from chia.protocols.farmer_protocol import SolutionResponse
from chia.protocols.outbound_message import Message, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.solver_protocol import SolverInfo
from chia.server.api_protocol import ApiMetadata
from chia.solver.solver import Solver


class SolverAPI:
    if TYPE_CHECKING:
        from chia.server.api_protocol import ApiProtocol

        _protocol_check: ClassVar[ApiProtocol] = cast("SolverAPI", None)

    log: logging.Logger
    solver: Solver
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def __init__(self, solver: Solver) -> None:
        self.log = logging.getLogger(__name__)
        self.solver = solver

    def ready(self) -> bool:
        return self.solver.started

    @metadata.request()
    async def solve(
        self,
        request: SolverInfo,
    ) -> Optional[Message]:
        if not self.solver.started:
            raise RuntimeError("Solver is not started")

        proof = self.solver.solve(request)
        if proof is None:
            return None

        response: SolutionResponse = SolutionResponse(
            proof=proof,
        )
        return make_msg(ProtocolMessageTypes.solution_resonse, response)
