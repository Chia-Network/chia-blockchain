from __future__ import annotations

import os
import sys
from ipaddress import IPv4Address, IPv6Address
from typing import Type, Union

import pytest

from chia.util.network import IPAddress, resolve


class TestNetwork:
    @pytest.mark.asyncio
    async def test_resolve4(self):
        # Run these tests forcing IPv4 resolution
        prefer_ipv6 = False
        assert await resolve("127.0.0.1", prefer_ipv6=prefer_ipv6) == IPAddress.create("127.0.0.1")
        assert await resolve("10.11.12.13", prefer_ipv6=prefer_ipv6) == IPAddress.create("10.11.12.13")
        assert await resolve("localhost", prefer_ipv6=prefer_ipv6) == IPAddress.create("127.0.0.1")
        assert await resolve("example.net", prefer_ipv6=prefer_ipv6) == IPAddress.create("93.184.216.34")

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        condition=("GITHUB_ACTIONS" in os.environ) and (sys.platform in {"darwin", "win32"}),
        reason="macOS and Windows runners in GitHub Actions do not seem to support IPv6",
    )
    async def test_resolve6(self):
        # Run these tests forcing IPv6 resolution
        prefer_ipv6 = True
        assert await resolve("::1", prefer_ipv6=prefer_ipv6) == IPAddress.create("::1")
        assert await resolve("2000:1000::1234:abcd", prefer_ipv6=prefer_ipv6) == IPAddress.create(
            "2000:1000::1234:abcd"
        )
        # ip6-localhost is not always available, and localhost is IPv4 only
        # on some systems.  Just test neither here.
        # assert await resolve("ip6-localhost", prefer_ipv6=prefer_ipv6) == IPAddress.create("::1")
        # assert await resolve("localhost", prefer_ipv6=prefer_ipv6) == IPAddress.create("::1")
        assert await resolve("example.net", prefer_ipv6=prefer_ipv6) == IPAddress.create(
            "2606:2800:220:1:248:1893:25c8:1946"
        )


@pytest.mark.parametrize(
    "address_string, expected_inner",
    [
        ("::1", IPv6Address),
        ("2000:1000::1234:abcd", IPv6Address),
        ("127.0.0.1", IPv4Address),
        ("10.11.12.13", IPv4Address),
        ("93.184.216.34", IPv4Address),
    ],
)
def test_ip_address(address_string: str, expected_inner: Type[Union[IPv4Address, IPv6Address]]) -> None:
    inner = expected_inner(address_string)
    ip = IPAddress.create(address_string)
    # Helpers
    assert ip.is_v4 == (expected_inner == IPv4Address)
    assert ip.is_v6 == (expected_inner == IPv6Address)
    # Overwritten dataclass methods
    assert int(ip) == int(inner)
    assert str(ip) == str(inner)
    assert repr(ip) == repr(inner)
    # Forwarded IPv4Address, IPV6Address properties
    assert ip.packed == inner.packed
    assert ip.is_private == inner.is_private
    # Still use dataclass comparison
    assert ip != inner


@pytest.mark.parametrize("address_string", ["10.11.12.13.14", "10,11.12.13", "0:::", "localhost", "invalid"])
def test_invalid_ip_addresses(address_string: str) -> None:
    with pytest.raises(ValueError):
        IPAddress.create(address_string)
