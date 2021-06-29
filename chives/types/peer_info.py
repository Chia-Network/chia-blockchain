import ipaddress
from dataclasses import dataclass
from typing import Optional, Union

from chia.util.ints import uint16, uint64
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class PeerInfo(Streamable):
    host: str
    port: uint16

    def is_valid(self, allow_private_subnets=False) -> bool:
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
    def get_key(self):
        try:
            ip = ipaddress.IPv6Address(self.host)
        except ValueError:
            ip_v4 = ipaddress.IPv4Address(self.host)
            ip = ipaddress.IPv6Address(int(ipaddress.IPv6Address("2002::")) | (int(ip_v4) << 80))
        key = ip.packed
        key += bytes([self.port // 0x100, self.port & 0x0FF])
        return key

    def get_group(self):
        # TODO: Port everything from Bitcoin.
        ipv4 = 1
        try:
            ip = ipaddress.IPv4Address(self.host)
        except ValueError:
            ip = ipaddress.IPv6Address(self.host)
            ipv4 = 0
        if ipv4:
            group = bytes([1]) + ip.packed[:2]
        else:
            group = bytes([0]) + ip.packed[:4]
        return group


@dataclass(frozen=True)
@streamable
class TimestampedPeerInfo(Streamable):
    host: str
    port: uint16
    timestamp: uint64
