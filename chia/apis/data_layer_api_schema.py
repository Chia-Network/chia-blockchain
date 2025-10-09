from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from chia.server.api_protocol import ApiMetadata, ApiSchemaProtocol


class DataLayerApiSchema:
    if TYPE_CHECKING:
        _protocol_check: ApiSchemaProtocol = cast("DataLayerApiSchema", None)

    metadata: ClassVar[ApiMetadata] = ApiMetadata()
