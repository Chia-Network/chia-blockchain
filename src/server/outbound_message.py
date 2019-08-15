from typing import Any
from dataclasses import dataclass


@dataclass
class OutboundMessage:
    peer_type: str
    function: str
    data: Any
    respond: bool
    broadcast: bool
