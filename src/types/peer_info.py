from src.util.streamable import streamable, Streamable
from src.util.ints import uint16
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class PeerInfo(Streamable):
    # TODO: Change `host` type to bytes16
    host: str
    port: uint16
