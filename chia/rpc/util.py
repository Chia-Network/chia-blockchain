import logging
import traceback
from typing import Callable, Dict, Union

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
            # TODO: create_error_response
            tb = traceback.format_exc()
            log.warning(f"Error while handling message: {tb}")
            if len(e.args) > 0:
                error = e.args[0]
            else:
                error = e

            res_object = {"success": False, "error": str(error), "traceback": tb}

        return obj_to_response(res_object)

    return inner


def create_error_response(exception: Exception) -> Dict[str, Union[bool, str]]:
    # TODO: do we really need to pick between e and e.args[0]?
    return {"success": False, "error": str(e), "traceback": traceback.format_exception(exception)}
