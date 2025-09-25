from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from chia.protocols import timelord_protocol
from chia.protocols.timelord_protocol import NewPeakTimelord
from chia.server.api_protocol import ApiMetadata, ApiSchemaProtocol


class TimelordApiSchema:
    if TYPE_CHECKING:
        _protocol_check: ApiSchemaProtocol = cast("TimelordApiSchema", None)

    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    @metadata.request()
    async def new_peak_timelord(self, new_peak: NewPeakTimelord) -> None: ...

    @metadata.request()
    async def new_unfinished_block_timelord(
        self, new_unfinished_block: timelord_protocol.NewUnfinishedBlockTimelord
    ) -> None: ...

    @metadata.request()
    async def request_compact_proof_of_time(self, vdf_info: timelord_protocol.RequestCompactProofOfTime) -> None: ...
