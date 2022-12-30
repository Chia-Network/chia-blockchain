from __future__ import annotations

import dataclasses
import json
from typing import Any

from aiohttp import web

from chia.wallet.util.wallet_types import WalletType


class EnhancedJSONEncoder(json.JSONEncoder):
    """
    Encodes bytes as hex strings with 0x, and converts all dataclasses to json.
    """

    def default(self, o: Any):
        if dataclasses.is_dataclass(o):
            return o.to_json_dict()
        elif isinstance(o, WalletType):
            return o.name
        elif hasattr(type(o), "__bytes__"):
            return f"0x{bytes(o).hex()}"
        elif isinstance(o, bytes):
            return f"0x{o.hex()}"
        return super().default(o)


def dict_to_json_str(o: Any) -> str:
    """
    Converts a python object into json.
    """
    json_str = json.dumps(o, cls=EnhancedJSONEncoder, sort_keys=True)
    return json_str


def obj_to_response(o: Any) -> web.Response:
    """
    Converts a python object into json. Used for RPC server which returns JSON.
    """
    json_str = dict_to_json_str(o)
    return web.Response(body=json_str, content_type="application/json")
