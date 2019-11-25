from dataclasses import dataclass

from src.server.connection import NodeType
from src.types.sized_bytes import bytes32
from src.util.cbor_message import cbor_message
from src.util.ints import uint16

protocol_version = "0.0.4"

"""
Handshake when establishing a connection between two servers.
"""


@dataclass(frozen=True)
@cbor_message
class Handshake:
    network_id: str
    version: str
    node_id: bytes32
    server_port: uint16
    node_type: NodeType


@dataclass(frozen=True)
@cbor_message
class HandshakeAck:
    pass


@dataclass(frozen=True)
@cbor_message
class Ping:
    pass


@dataclass(frozen=True)
@cbor_message
class Pong:
    pass
