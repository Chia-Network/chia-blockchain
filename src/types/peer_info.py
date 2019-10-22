from src.util.streamable import streamable, Streamable
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class PeerInfo(Streamable):
    host: str
    port: uint32
    node_id: bytes32
