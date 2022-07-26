import os
import sys

import pytest
from chia.util.network import get_host_addr


class TestNetwork:
    @pytest.mark.asyncio
    async def test_get_host_addr4(self):
        # Run these tests forcing IPv4 resolution
        prefer_ipv6 = False
        assert get_host_addr("127.0.0.1", prefer_ipv6) == "127.0.0.1"
        assert get_host_addr("10.11.12.13", prefer_ipv6) == "10.11.12.13"
        assert get_host_addr("localhost", prefer_ipv6) == "127.0.0.1"
        assert get_host_addr("example.net", prefer_ipv6) == "93.184.216.34"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        condition=("GITHUB_ACTIONS" in os.environ) and (sys.platform in {"darwin", "win32"}),
        reason="macOS and Windows runners in GitHub Actions do not seem to support IPv6",
    )
    async def test_get_host_addr6(self):
        # Run these tests forcing IPv6 resolution
        prefer_ipv6 = True
        assert get_host_addr("::1", prefer_ipv6) == "::1"
        assert get_host_addr("2000:1000::1234:abcd", prefer_ipv6) == "2000:1000::1234:abcd"
        # ip6-localhost is not always available, and localhost is IPv4 only
        # on some systems.  Just test neither here.
        # assert get_host_addr("ip6-localhost", prefer_ipv6) == "::1"
        # assert get_host_addr("localhost", prefer_ipv6) == "::1"
        assert get_host_addr("example.net", prefer_ipv6) == "2606:2800:220:1:248:1893:25c8:1946"
