from __future__ import annotations

import logging
from typing import ClassVar, Optional

from typing_extensions import Protocol

from chia.protocols.outbound_message import Message
from chia.protocols.solver_protocol import SolverInfo
from chia.server.api_protocol import ApiMetadata, ApiProtocol


class SolverApiStub(ApiProtocol, Protocol):
    """Non-functional API stub for SolverAPI

    This is a protocol definition only - methods are not implemented and should
    never be called. Use the actual SolverAPI implementation at runtime.
    """

    log: logging.Logger
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the solver is ready."""
        ...

    @metadata.request(peer_required=False)
    async def solve(self, request: SolverInfo) -> Optional[Message]:
        """Handle solver request."""
        ...
