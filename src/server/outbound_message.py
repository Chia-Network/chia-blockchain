from typing import Any
from enum import Enum
from dataclasses import dataclass


class NodeType(Enum):
    FULL_NODE = 1
    PLOTTER = 2
    FARMER = 3
    TIMELORD = 4


class Delivery(Enum):
    # A message is sent to the same peer that we received a message from
    RESPOND = 1
    # A message is sent to all peers
    BROADCAST = 2
    # A message is sent to all peers except the one from which we received the API call
    BROADCAST_TO_OTHERS = 3
    # A message is sent to a random peer
    RANDOM = 4


@dataclass
class Message:
    # Function to call
    function: str
    # Message data for that function call
    data: Any


@dataclass
class OutboundMessage:
    # Type of the peer, 'farmer', 'plotter', 'full_node', etc.
    peer_type: NodeType
    # Message to send
    message: Message
    delivery_method: Delivery
