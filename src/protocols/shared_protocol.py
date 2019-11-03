from src.util.cbor_message import cbor_message
from src.types.sized_bytes import bytes32
from dataclasses import dataclass

protocol_version = "0.0.1"

"""
Handshake when establishing a connection between two servers.
"""
@dataclass(frozen=True)
@cbor_message
class Handshake:
    version: str
    node_id: bytes32


@dataclass(frozen=True)
@cbor_message
class HandshakeAck:
    pass
