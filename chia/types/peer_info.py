from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Optional, Union

from chia.util.ints import uint16, uint64
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
class PeerInfo:
    host: str
    port: uint16

    def is_valid(self, allow_private_subnets: bool = False) -> bool:
        ip: Optional[Union[ipaddress.IPv6Address, ipaddress.IPv4Address]] = None
        try:
            ip = ipaddress.IPv6Address(self.host)
        except ValueError:
            ip = None
        if ip is not None:
            if ip.is_private and not allow_private_subnets:
                return False
            return True

        try:
            ip = ipaddress.IPv4Address(self.host)
        except ValueError:
            ip = None
        if ip is not None:
            if ip.is_private and not allow_private_subnets:
                return False
            return True
        return False

    # Functions related to peer bucketing in new/tried tables.
    def get_key(self) -> bytes:
        try:
            ip = ipaddress.IPv6Address(self.host)
        except ValueError:
            ip_v4 = ipaddress.IPv4Address(self.host)
            ip = ipaddress.IPv6Address(int(ipaddress.IPv6Address("2002::")) | (int(ip_v4) << 80))
        key = ip.packed
        key += bytes([self.port // 0x100, self.port & 0x0FF])
        return key

    def get_group(self) -> bytes:
        # TODO: Port everything from Bitcoin.
        ip_v4: Optional[ipaddress.IPv4Address] = None
        ip_v6: Optional[ipaddress.IPv6Address] = None
        try:
            ip_v4 = ipaddress.IPv4Address(self.host)
        except ValueError:
            ip_v6 = ipaddress.IPv6Address(self.host)
        if ip_v4 is not None:
            group = bytes([1]) + ip_v4.packed[:2]
        elif ip_v6 is not None:
            group = bytes([0]) + ip_v6.packed[:4]
        else:
            raise ValueError("PeerInfo.host is not an ip address")
        return group


@streamable
@dataclass(frozen=True)
class TimestampedPeerInfo(Streamable):
    host: str
    port: uint16
    timestamp: uint64
