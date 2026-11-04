from __future__ import annotations

from typing import TYPE_CHECKING, Any, get_type_hints

from chia.rpc.util import MarshallableRpcEndpoint, RpcEndpoint
from chia.util.streamable import Streamable
from chia.wallet.util.blind_signer_tl import BLIND_SIGNER_TRANSLATION
from chia.wallet.util.clvm_streamable import (
    TranslationLayer,
    json_deserialize_with_clvm_streamable,
    json_serialize_with_clvm_streamable,
)

if TYPE_CHECKING:
    from chia.rpc.rpc_server import EndpointResult


ALL_TRANSLATION_LAYERS: dict[str, TranslationLayer] = {"CHIP-0028": BLIND_SIGNER_TRANSLATION}


def marshal(func: MarshallableRpcEndpoint) -> RpcEndpoint:
    hints = get_type_hints(func)
    request_hint = hints["request"]
    assert issubclass(request_hint, Streamable)
    request_class = request_hint

    async def rpc_endpoint(self: object, request: dict[str, Any], *args: object, **kwargs: object) -> EndpointResult:
        response_obj: Streamable = await func(
            self,
            (
                request_class.from_json_dict(request)
                if not request.get("CHIP-0029", False)
                else json_deserialize_with_clvm_streamable(
                    request,
                    request_hint,
                    translation_layer=(
                        ALL_TRANSLATION_LAYERS[request["translation"]] if "translation" in request else None
                    ),
                )
            ),
            *args,
            **kwargs,
        )
        if not request.get("CHIP-0029", False):
            return response_obj.to_json_dict()
        else:
            response_dict = json_serialize_with_clvm_streamable(
                response_obj,
                translation_layer=(
                    ALL_TRANSLATION_LAYERS[request["translation"]] if "translation" in request else None
                ),
            )
            if isinstance(response_dict, str):  # pragma: no cover
                raise ValueError("Internal Error. Marshalled endpoint was made with clvm_streamable.")
            return response_dict

    rpc_endpoint.__name__ = func.__name__
    return rpc_endpoint
