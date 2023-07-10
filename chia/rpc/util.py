from __future__ import annotations

import logging
import traceback
from typing import Any, Callable, Coroutine, Dict

import aiohttp

from chia.util.json_util import obj_to_response

log = logging.getLogger(__name__)


def wrap_http_handler(f) -> Callable:
    async def inner(request) -> aiohttp.web.Response:
        request_data = await request.json()
        try:
            res_object = await f(request_data)
            if res_object is None:
                res_object = {}
            if "success" not in res_object:
                res_object["success"] = True
        except Exception as e:
            tb = traceback.format_exc()
            log.warning(f"Error while handling message: {tb}")
            if len(e.args) > 0:
                res_object = {"success": False, "error": f"{e.args[0]}"}
            else:
                res_object = {"success": False, "error": f"{e}"}

        return obj_to_response(res_object)

    return inner


def potentially_inside_lock(
    func: Callable[..., Coroutine[Any, Any, Dict[str, Any]]]
) -> Callable[..., Coroutine[Any, Any, Dict[str, Any]]]:
    async def rpc_endpoint(self, *args, hold_lock=True, **kwargs) -> Dict[str, Any]:
        return await func(self, *args, hold_lock, **kwargs)

    return rpc_endpoint
