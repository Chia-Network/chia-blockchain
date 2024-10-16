from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Union


@dataclass(frozen=True)
class IPAddress:
    _inner: Union[IPv4Address, IPv6Address]

    @classmethod
    def create(cls, ip: str) -> IPAddress:
        return cls(ip_address(ip))

    def __int__(self) -> int:
        return int(self._inner)

    def __str__(self) -> str:
        return str(self._inner)

    def __repr__(self) -> str:
        return repr(self._inner)

    @property
    def packed(self) -> bytes:
        return self._inner.packed

    @property
    def is_private(self) -> bool:
        return self._inner.is_private

    @property
    def is_v4(self) -> bool:
        return self._inner.version == 4

    @property
    def is_v6(self) -> bool:
        return self._inner.version == 6
