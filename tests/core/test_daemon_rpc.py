import pytest

from tests.setup_nodes import setup_daemon
from chinilla.daemon.client import connect_to_daemon
from tests.setup_nodes import bt
from chinilla import __version__


class TestDaemonRpc:
    @pytest.fixture(scope="function")
    async def get_daemon(self):
        async for _ in setup_daemon(btools=bt):
            yield _

    @pytest.mark.asyncio
    async def test_get_version_rpc(self, get_daemon):
        config = bt.config
        client = await connect_to_daemon(config["self_hostname"], config["daemon_port"], bt.get_daemon_ssl_context())
        response = await client.get_version()

        assert response["data"]["success"]
        assert response["data"]["version"] == __version__
