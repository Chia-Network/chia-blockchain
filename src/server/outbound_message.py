from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Optional

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.util.ints import uint8, uint16
from chia.util.streamable import Streamable, streamable


class NodeType(IntEnum):
    FULL_NODE = 1
    HARVESTER = 2
    FARMER = 3
    TIMELORD = 4
    INTRODUCER = 5
    WALLET = 6


class Delivery(IntEnum):
    # A message is sent to the same peer that we received a message from
    RESPOND = 1
    # A message is sent to all peers
    BROADCAST = 2
    # A message is sent to all peers except the one from which we received the API call
    BROADCAST_TO_OTHERS = 3
    # A message is sent to a random peer
    RANDOM = 4
    # Pseudo-message to close the current connection
    CLOSE = 5
    # A message is sent to a speicific peer
    SPECIFIC = 6


@dataclass(frozen=True)
@streamable
class Message(Streamable):
    type: uint8  # one of ProtocolMessageTypes
    # message id
    id: Optional[uint16]
    # Message data for that type
    data: bytes


def make_msg(msg_type: ProtocolMessageTypes, data: Any) -> Message:
    return Message(uint8(msg_type.value), None, bytes(data))
