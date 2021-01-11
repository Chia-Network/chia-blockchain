from dataclasses import dataclass

from src.util.ints import uint16, uint64
from src.util.streamable import Streamable, streamable

import ipaddress


@dataclass(frozen=True)
@streamable
class PeerInfo(Streamable):
    host: str
    port: uint16

    def is_valid(self):
        if self.host == "127.0.0.1" or self.host == "localhost":
            return True

        ip = None
        try:
            ip = ipaddress.IPv6Address(self.host)
        except ValueError:
            ip = None
        if ip is not None:
            if ip.is_private:
                return False
            return True

        try:
            ip = ipaddress.IPv4Address(self.host)
        except ValueError:
            ip = None
        if ip is not None:
            if ip.is_private:
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
