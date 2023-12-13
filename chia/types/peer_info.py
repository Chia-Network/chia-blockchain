from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Union

from chia.util.ints import uint16, uint64
from chia.util.network import IPAddress
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
class UnresolvedPeerInfo:
    host: str
    port: uint16


# TODO, Replace unsafe_hash with frozen and drop the __init__ as soon as all PeerInfo call sites pass in an IPAddress.
@dataclass(unsafe_hash=True)
class PeerInfo:
    _ip: IPAddress
    _port: uint16

    # TODO, Drop this as soon as all call PeerInfo calls pass in an IPAddress
    def __init__(self, host: Union[IPAddress, str], port: int):
        self._ip = host if isinstance(host, IPAddress) else IPAddress.create(host)
        self._port = uint16(port)

    # Kept here for compatibility until all places where its used transitioned to IPAddress instead of str.
    @property
    def host(self) -> str:
        return str(self._ip)

    @property
    def ip(self) -> IPAddress:
        return self._ip

    @property
    def port(self) -> uint16:
        return self._port

    # Functions related to peer bucketing in new/tried tables.
    def get_key(self) -> bytes:
        if self.ip.is_v4:
            key = ipaddress.IPv6Address(int(ipaddress.IPv6Address("2002::")) | (int(self.ip) << 80)).packed
        else:
            key = self.ip.packed
        key += bytes([self.port // 0x100, self.port & 0x0FF])
        return key

    def get_group(self) -> bytes:
        # TODO: Port everything from Bitcoin.
        if self.ip.is_v4:
            return bytes([1]) + self.ip.packed[:2]
        else:
            return bytes([0]) + self.ip.packed[:4]


@streamable
@dataclass(frozen=True)
class TimestampedPeerInfo(Streamable):
    host: str
    port: uint16
    timestamp: uint64
