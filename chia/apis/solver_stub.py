from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Optional, cast

if TYPE_CHECKING:
    from chia.server.api_protocol import ApiProtocol

# Minimal imports to avoid circular dependencies
from chia.protocols.outbound_message import Message
from chia.protocols.solver_protocol import SolverInfo
from chia.server.api_protocol import ApiMetadata


class SolverApiStub:
    """Lightweight API stub for SolverAPI to break circular dependencies."""

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ApiProtocol] = cast("SolverApiStub", None)

    log: logging.Logger
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the solver is ready."""
        return True

    @metadata.request(peer_required=False)
    async def solve(self, request: SolverInfo) -> Optional[Message]:
        """Handle solver request."""
        return None
