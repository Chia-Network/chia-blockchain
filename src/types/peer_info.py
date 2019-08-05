from src.util.streamable import streamable
from src.types.sized_bytes import bytes4
from src.util.ints import uint32


@streamable
class PeerInfo:
    ip: bytes4
    port: uint32
