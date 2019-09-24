from src.util.cbor_message import cbor_message
from src.types.sized_bytes import bytes32

protocol_version = "0.0.1"

"""
Handshake when establishing a connection between two servers.
"""
@cbor_message(tag=7000)
class Handshake:
    version: str
    node_id: bytes32


@cbor_message(tag=7001)
class HandshakeAck:
    pass
