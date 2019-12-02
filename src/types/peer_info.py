from dataclasses import dataclass
from typing import Union

from src.types.sized_bytes import bytes16
from src.util.ints import uint16
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class BinPeerInfo(Streamable):
    host: bytes16
    port: uint16


@dataclass(frozen=True)
class PeerInfo:
    host: str
    port: uint16


AnyPeerInfo = Union[BinPeerInfo, PeerInfo]
