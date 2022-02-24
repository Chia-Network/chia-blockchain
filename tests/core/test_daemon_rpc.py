import pytest
import pytest_asyncio

from tests.setup_nodes import setup_daemon
from chia.daemon.client import connect_to_daemon
from tests.setup_nodes import bt
from chia import __version__
from tests.util.socket import find_available_listen_port
from chia.util.config import save_config


class TestDaemonRpc:
    @pytest_asyncio.fixture(scope="function")
    async def get_daemon(self):
        bt._config["daemon_port"] = find_available_listen_port()
        # unfortunately, the daemon's WebSocketServer loads the configs from
        # disk, so the only way to configure its port is to write it to disk
        save_config(bt.root_path, "config.yaml", bt._config)
        async for _ in setup_daemon(btools=bt):
            yield _

    @pytest.mark.asyncio
    async def test_get_version_rpc(self, get_daemon):
        config = bt.config
        client = await connect_to_daemon(config["self_hostname"], config["daemon_port"], bt.get_daemon_ssl_context())
        response = await client.get_version()

        assert response["data"]["success"]
        assert response["data"]["version"] == __version__
