from dataclasses import dataclass

from src.util.ints import uint16
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class PeerInfo(Streamable):
    # TODO: Change `host` type to bytes16
    host: str
    port: uint16
