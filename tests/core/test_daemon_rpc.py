import pytest
import pytest_asyncio

from chia import __version__
from chia.daemon.client import connect_to_daemon
from tests.setup_nodes import setup_daemon


@pytest_asyncio.fixture(scope="function")
async def get_daemon(bt):
    async for _ in setup_daemon(btools=bt):
        yield _


class TestDaemonRpc:
    @pytest.mark.asyncio
    async def test_get_version_rpc(self, get_daemon, bt):
        ws_server = get_daemon
        config = bt.config
        client = await connect_to_daemon(
            config["self_hostname"], config["daemon_port"], 50 * 1000 * 1000, bt.get_daemon_ssl_context()
        )
        response = await client.get_version()

        assert response["data"]["success"]
        assert response["data"]["version"] == __version__
        ws_server.stop()
