from __future__ import annotations

import logging
import traceback
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, Callable, get_type_hints

import aiohttp

from chia.util.json_util import obj_to_response
from chia.util.streamable import Streamable
from chia.wallet.util.blind_signer_tl import BLIND_SIGNER_TRANSLATION
from chia.wallet.util.clvm_streamable import (
    TranslationLayer,
    json_deserialize_with_clvm_streamable,
    json_serialize_with_clvm_streamable,
)

log = logging.getLogger(__name__)

# TODO: consolidate this with chia.rpc.rpc_server.Endpoint
# Not all endpoints only take a dictionary so that definition is imperfect
# This definition is weaker than that one however because the arguments can be anything
RpcEndpoint = Callable[..., Awaitable[dict[str, Any]]]
MarshallableRpcEndpoint = Callable[..., Awaitable[Streamable]]
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


def wrap_http_handler(
    f: Callable[[dict[str, Any]], Awaitable[EndpointResult]],
    route: str,
) -> Callable[[aiohttp.web.Request], Awaitable[aiohttp.web.StreamResponse]]:
    async def inner(request: aiohttp.web.Request) -> aiohttp.web.StreamResponse:
        request_data = await request.json()
        try:
            res_object = await f(request_data)
            if res_object is None:
                res_object = {}
            if "success" not in res_object:
                res_object["success"] = True
        except Exception as e:
            tb = traceback.format_exc()
            log.warning(f"Error while handling message for {route}: {tb}")
            if len(e.args) > 0:
                res_object = {"success": False, "error": f"{e.args[0]}", "traceback": f"{tb}"}
            else:
                res_object = {"success": False, "error": f"{e}"}

        return obj_to_response(res_object)

    return inner
