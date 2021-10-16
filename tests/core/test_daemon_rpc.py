import pytest

from tests.setup_nodes import setup_daemon
from chia.daemon.client import connect_to_daemon
from tests.setup_nodes import bt
from chia import __version__

class TestDaemonRpc:
    @pytest.mark.asyncio
    async def test_get_version_rpc(self):
        config = bt.config

        async for _ in setup_daemon(bt):
            connection = await connect_to_daemon(config["self_hostname"], config["daemon_port"], bt.get_daemon_ssl_context())
            response = await connection.get_version()
            assert response is not None
            assert response["data"]["success"] == True
            assert response["data"]["version"] == __version__
            