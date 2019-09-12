from src.util.streamable import streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint32


@streamable
class PeerInfo:
    host: str
    port: uint32
    node_id: bytes32
