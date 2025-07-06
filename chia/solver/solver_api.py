from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, ClassVar, Optional, Union, cast

import aiohttp
from chia.protocols.outbound_message import  make_msg
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64

from chia import __version__
from chia.protocols.farmer_protocol import SolutionResponse
from chia.protocols.outbound_message import Message
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
        return make_msg(ProtocolMessageTypes.solution_resonse,response)
        