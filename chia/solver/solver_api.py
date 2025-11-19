from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from chia.protocols.outbound_message import Message, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.solver_protocol import SolverInfo, SolverResponse
from chia.server.api_protocol import ApiMetadata
from chia.solver.solver import Solver


class SolverAPI:
    if TYPE_CHECKING:
        from chia.apis.solver_stub import SolverApiStub

        # Verify this class implements the SolverApiStub protocol
        def _protocol_check(self: SolverAPI) -> SolverApiStub:
            return self

    log: logging.Logger
    solver: Solver
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def __init__(self, solver: Solver) -> None:
        self.log = logging.getLogger(__name__)
        self.solver = solver

    def ready(self) -> bool:
        return self.solver.started

    @metadata.request(peer_required=False, reply_types=[ProtocolMessageTypes.solution_response])
    async def solve(
        self,
        request: SolverInfo,
    ) -> Message | None:
        """
        Solve a V2 plot partial proof to get the full proof of space.
        This is called by the farmer when it receives V2 parital proofs from harvester.
        """
        if not self.solver.started:
            self.log.error("Solver is not started")
            return None

        self.log.debug(f"Solving partial {request.partial_proof.proof_fragments[:5]}")

        try:
            proof = self.solver.solve(request.partial_proof, request.plot_id, request.strength, request.size)
            if proof is None:
                self.log.warning(f"Solver returned no proof for parital {request.partial_proof.proof_fragments[:5]}")
                return None

            self.log.debug(f"Successfully solved partial proof, returning {len(proof)} byte proof")
            return make_msg(
                ProtocolMessageTypes.solution_response,
                SolverResponse(proof=proof, partial_proof=request.partial_proof),
            )

        except Exception as e:
            self.log.error(f"Error solving parital {request.partial_proof.proof_fragments[:5]}: {e}")
            return None
