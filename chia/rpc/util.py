from __future__ import annotations

import logging
import traceback
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import aiohttp

from chia.rpc.rpc_errors import structured_error_from_exception
from chia.util.json_util import obj_to_response
from chia.util.streamable import Streamable

log = logging.getLogger(__name__)

# TODO: consolidate this with chia.rpc.rpc_server.Endpoint
# Not all endpoints only take a dictionary so that definition is imperfect
# This definition is weaker than that one however because the arguments can be anything
RpcEndpoint = Callable[..., Awaitable[dict[str, Any]]]
MarshallableRpcEndpoint = Callable[..., Awaitable[Streamable]]
if TYPE_CHECKING:
    from chia.rpc.rpc_server import EndpointResult


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
            error_message, structured = structured_error_from_exception(e)
            res_object = {
                "success": False,
                "error": error_message,
                "traceback": tb,
                "structuredError": structured,
            }

        return obj_to_response(res_object)

    return inner
