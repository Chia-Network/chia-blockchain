from typing import Any
import secrets
import dataclasses
import json
from aiohttp import web

from src.types.sized_bytes import bytes32


def create_node_id() -> bytes32:
    """Generates a transient random node_id."""
    return bytes32(secrets.token_bytes(32))


class EnhancedJSONEncoder(json.JSONEncoder):
    """
    Encodes bytes as hex strings with 0x, and converts all dataclasses to json.
    Used for RPC server which returns JSON.
    """

    def default(self, o: Any):
        if dataclasses.is_dataclass(o):
            return o.to_json_dict()
        elif hasattr(type(o), "__bytes__"):
            return f"0x{bytes(o).hex()}"
        elif isinstance(o, bytes):
            return f"0x{o.hex()}"
        return super().default(o)


def obj_to_response(o: Any) -> web.Response:
    """
    Converts a python object into json. Used for RPC server which returns JSON.
    """
    json_str = json.dumps(o, cls=EnhancedJSONEncoder, sort_keys=True)
    return web.Response(body=json_str, content_type="application/json")
