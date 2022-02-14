import pytest

from tests.setup_nodes import setup_daemon
from chia.daemon.client import connect_to_daemon
from chia.util.network import get_host_addr
from tests.setup_nodes import bt
from chia import __version__


class TestDaemonRpc:
    @pytest.fixture(scope="function")
    async def get_daemon(self):
        async for _ in setup_daemon(btools=bt):
            yield _

    @pytest.mark.asyncio
    async def test_get_version_rpc(self, get_daemon):
        config = bt.config
        prefer_ipv6 = config["prefer_ipv6"]
        host = get_host_addr(host=config["self_hostname"], prefer_ipv6=prefer_ipv6)

        client = await connect_to_daemon(host, config["daemon_port"], bt.get_daemon_ssl_context())
        response = await client.get_version()

        assert response["data"]["success"]
        assert response["data"]["version"] == __version__
