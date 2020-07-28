from dataclasses import dataclass

from src.util.ints import uint16, uint64
from src.util.streamable import Streamable, streamable

import ipaddress


@dataclass(frozen=True, init=False, eq=False)
@streamable
class PeerInfo(Streamable):
    # TODO: Change `host` type to bytes16
    host: str
    port: uint16
    timestamp: uint64

    def __init__(self, host, port, timestamp=0):
        object.__setattr__(self, 'host', host)
        object.__setattr__(self, 'port', port)
        object.__setattr__(self, 'timestamp', uint64(timestamp))

    def __eq__(self, other):
        return (self.host == other.host and self.port == other.port)

    def get_key(self):
        try:
            ip = ipaddress.IPv6Address(self.host)
        except ValueError:
            ip_v4 = ipaddress.IPv4Address(self.host)
            ip = ipaddress.IPv6Address(
                int(ipaddress.IPv6Address("2002::"))
                | (int(ip_v4) << 80)
            )
        key = ip.packed
        key += bytes(
            [
                self.port // 0x100,
                self.port & 0x0FF,
            ]
        )
        return key

    def get_group(self):
        # TODO: Port everything from Bitcoin.
        ipv4 = 1
        try:
            ip = ipaddress.IPv4Address(
                self.host
            )
        except ValueError:
            ip = ipaddress.IPv6Address(
                self.host
            )
            ipv4 = 0
        if ipv4 == 0:
            group = bytes([0]) + ip.packed[:2]
        else:
            group = bytes([1]) + ip.packed[:4]
        return group
