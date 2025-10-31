from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, cast

if TYPE_CHECKING:
    from chia.server.api_protocol import ApiProtocol

# Minimal imports to avoid circular dependencies
from chia.protocols.timelord_protocol import NewPeakTimelord, NewUnfinishedBlockTimelord, RequestCompactProofOfTime
from chia.server.api_protocol import ApiMetadata


class TimelordApiStub:
    """Non-functional API stub for TimelordAPI to break circular dependencies.

    This is a protocol definition only - methods are not implemented and should
    never be called. Use the actual TimelordAPI implementation at runtime.
    """

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ApiProtocol] = cast("TimelordApiStub", None)

    log: logging.Logger
    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    def ready(self) -> bool:
        """Check if the timelord is ready."""
        ...

    @metadata.request()
    async def new_peak_timelord(self, new_peak: NewPeakTimelord) -> None:
        """Handle new peak from full node."""
        ...

    @metadata.request()
    async def new_unfinished_block_timelord(self, new_unfinished_block: NewUnfinishedBlockTimelord) -> None:
        """Handle new unfinished block from full node."""
        ...

    @metadata.request()
    async def request_compact_proof_of_time(self, vdf_info: RequestCompactProofOfTime) -> None:
        """Handle request for compact proof of time."""
        ...
