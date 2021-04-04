from dataclasses import dataclass
from enum import IntEnum
from typing import List, Tuple

from chia.util.ints import uint8, uint16
from chia.util.streamable import Streamable, streamable

protocol_version = "0.0.32"

"""
Handshake when establishing a connection between two servers.
Note: When changing this file, also change protocol_message_types.py
"""


# Capabilities can be added here when new features are added to the protocol
# These are passed in as uint16 into the Handshake
class Capability(IntEnum):
    BASE = 1  # Base capability just means it supports the chia protocol at mainnet


@dataclass(frozen=True)
@streamable
class Handshake(Streamable):
    network_id: str
    protocol_version: str
    software_version: str
    server_port: uint16
    node_type: uint8
    capabilities: List[Tuple[uint16, str]]
