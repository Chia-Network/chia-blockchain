from typing import Any
from dataclasses import dataclass


@dataclass
class OutboundMessage:
    # Type of the peer, 'farmer', 'plotter', 'full_node', etc.
    peer_type: str
    # Function to call
    function: str
    # Message data for that function call
    data: Any
    # If true, a message is sent to the same peer that we received a message from
    respond: bool
    # If true, a message is sent to all other peers
    broadcast: bool
