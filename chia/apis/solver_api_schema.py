from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional, cast

from chia.protocols.outbound_message import Message
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.solver_protocol import SolverInfo
from chia.server.api_protocol import ApiMetadata, ApiSchemaProtocol


class SolverApiSchema:
    if TYPE_CHECKING:
        _protocol_check: ApiSchemaProtocol = cast("SolverApiSchema", None)

    metadata: ClassVar[ApiMetadata] = ApiMetadata()

    @metadata.request(peer_required=False, reply_types=[ProtocolMessageTypes.solution_response])
    async def solve(
        self,
        request: SolverInfo,
    ) -> Optional[Message]: ...
