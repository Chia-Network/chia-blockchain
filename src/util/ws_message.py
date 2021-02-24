from secrets import token_bytes
from typing import Dict, Any, Optional, Union, TypedDict

from src.util.json_util import dict_to_json_str


# Messages must follow this format
# Message = { "command" "command_name",
#             "data" : {...},
#             "request_id": "bytes_32",
#             "destination": "service_name",
#             "origin": "service_name"
#           }


Request = TypedDict(
    "Request", {"command": str, "data": Optional[Dict[str, Any]], "request_id": str, "destination": str, "origin": str}
)
Response = TypedDict(
    "Response",
    {
        "command": str,
        "ack": bool,
        "data": Optional[Dict[str, Any]],
        "request_id": str,
        "destination": str,
        "origin": str,
    },
)


def format_response(incoming_msg: Request, response_data: Dict[str, Any]) -> str:
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


def create_payload(
    command: str, data: Optional[Dict[str, Any]], origin: str, destination: str, string=True
) -> Union[Response, str]:
    response = Response(
        command=command,
        ack=False,
        data=data,
        request_id=token_bytes().hex(),
        destination=destination,
        origin=origin,
    )

    if string:
        json_str = dict_to_json_str(response)
        return json_str
    else:
        return response


def pong():
    response = {"success": True}
    return response
