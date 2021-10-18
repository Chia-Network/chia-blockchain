import pytest
from chia.util.network import get_host_addr


class TestNetwork:
    @pytest.mark.asyncio
    async def test_get_host_addr4(self):
        # TODO: Can I mock config here, rather than passing an override arg?
        prefer_ipv6 = False
        assert get_host_addr("127.0.0.1", prefer_ipv6) == "127.0.0.1"
        assert get_host_addr("10.11.12.13", prefer_ipv6) == "10.11.12.13"
        assert get_host_addr("localhost", prefer_ipv6) == "127.0.0.1"
        assert get_host_addr("example.net", prefer_ipv6) == "93.184.216.34"

    @pytest.mark.asyncio
    async def test_get_host_addr6(self):
        # TODO: Can I mock config here, rather than passing an override arg?
        prefer_ipv6 = True
        assert get_host_addr("::1", prefer_ipv6) == "::1"
        assert get_host_addr("2000:1000::1234:abcd", prefer_ipv6) == "2000:1000::1234:abcd"
        assert get_host_addr("ip6-localhost", prefer_ipv6) == "::1"
        assert get_host_addr("example.net", prefer_ipv6) == "2606:2800:220:1:248:1893:25c8:1946"
