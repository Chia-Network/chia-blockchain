from dataclasses import dataclass

from src.server.outbound_message import NodeType
from src.types.sized_bytes import bytes32
from src.util.ints import uint16
from src.util.streamable import streamable, Streamable

protocol_version = "0.0.25"

"""
Handshake when establishing a connection between two servers.
"""


@dataclass(frozen=True)
@streamable
class Handshake(Streamable):
    network_id: str
    version: str
    server_port: uint16
    node_type: NodeType


@dataclass(frozen=True)
@streamable
class HandshakeAck(Streamable):
    pass


@dataclass(frozen=True)
@streamable
class Ping(Streamable):
    nonce: bytes32


@dataclass(frozen=True)
@streamable
class Pong(Streamable):
    nonce: bytes32
