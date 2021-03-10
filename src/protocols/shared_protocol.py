from dataclasses import dataclass

from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint8, uint16
from src.util.streamable import Streamable, streamable

protocol_version = "0.0.32"

"""
Handshake when establishing a connection between two servers.
Note: When changing this file, also change protocol_message_types.py
"""


@dataclass(frozen=True)
@streamable
class Handshake(Streamable):
    network_id: bytes32
    protocol_version: str
    software_version: str
    server_port: uint16
    node_type: uint8


@dataclass(frozen=True)
@streamable
class HandshakeAck(Streamable):
    pass
