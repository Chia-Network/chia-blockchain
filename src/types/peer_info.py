from dataclasses import dataclass
from typing import Union

from src.types.sized_bytes import bytes16
from src.util.ints import uint16
from src.util.ip_str import ip_to_str
from src.util.streamable import Streamable, streamable


class IPAddr(bytes16):
    def __repr__(self):
        return f"'{ip_to_str(self)}'"


@dataclass(frozen=True)
@streamable
class BinPeerInfo(Streamable):
    host: IPAddr
    port: uint16


@dataclass(frozen=True)
class PeerInfo:
    host: str
    port: uint16


AnyPeerInfo = Union[BinPeerInfo, PeerInfo]
