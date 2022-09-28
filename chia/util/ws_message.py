from secrets import token_bytes
from typing import Any, Dict, Optional

from chia.util.json_util import dict_to_json_str

from typing_extensions import TypedDict


# Messages must follow this format
# Message = { "command" "command_name",
#             "data" : {...},
#             "request_id": "bytes_32",
#             "destination": "service_name",
#             "origin": "service_name"
#           }


class WsRpcMessage(TypedDict):
    command: str
    ack: bool
    data: Dict[str, Any]
    request_id: str
    destination: str
    origin: str


def format_response(incoming_msg: WsRpcMessage, response_data: Dict[str, Any]) -> str:
    """
    Formats the response into standard format.
    """
    response = {
        "command": incoming_msg["command"],
        "ack": True,
        "data": response_data,
        "request_id": incoming_msg["request_id"],
        "destination": incoming_msg["origin"],
        "origin": incoming_msg["destination"],
    }

    json_str = dict_to_json_str(response)
    return json_str


def create_payload(command: str, data: Dict[str, Any], origin: str, destination: str) -> str:
    response = create_payload_dict(command, data, origin, destination)
    return dict_to_json_str(response)


def create_payload_dict(command: str, data: Optional[Dict[str, Any]], origin: str, destination: str) -> WsRpcMessage:
    if data is None:
        data = {}

    return WsRpcMessage(
        command=command,
        ack=False,
        data=data,
        request_id=token_bytes().hex(),
        destination=destination,
        origin=origin,
    )


def pong() -> Dict[str, Any]:
    response = {"success": True}
    return response
