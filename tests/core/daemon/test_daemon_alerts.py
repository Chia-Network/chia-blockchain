import asyncio

import pytest
from blspy import PrivateKey

from src.util.hash import std_hash
from src.util.validate_alert import create_alert_file, create_not_ready_alert_file
from tests.setup_nodes import setup_daemon
from tests.util.alert_server import AlertServer
from tests.time_out_assert import time_out_assert

master_int = 5399117110774477986698372024995405256382522670366369834617409486544348441851
master_sk: PrivateKey = PrivateKey.from_bytes(master_int.to_bytes(32, "big"))
pubkey_alert = bytes(master_sk.get_g1()).hex()


class TestDaemonAlerts:
    @pytest.fixture(scope="function")
    async def get_daemon(self):
        async for _ in setup_daemon(55401, "http://127.0.0.1:59000/status", pubkey_alert):
            yield _

    @pytest.mark.asyncio
    async def test_alert(self, get_daemon):
        daemon = get_daemon
        selected = daemon.net_config["selected_network"]
        assert daemon.net_config["network_overrides"]["constants"][selected]["GENESIS_CHALLENGE"] is None
        alert_file_path = daemon.root_path / "alert.txt"

        alert_server = await AlertServer.create_alert_server(alert_file_path, 59000)
        create_not_ready_alert_file(alert_file_path, master_sk)
        await alert_server.run()
        expected_genesis = None

        def check_genesis(expected):
            return daemon.net_config["network_overrides"]["constants"][selected]["GENESIS_CHALLENGE"] == expected

        await asyncio.sleep(10)
        await time_out_assert(15, check_genesis, True, expected_genesis)

        preimage = "This is test preimage!"
        expected_genesis = std_hash(bytes(preimage, "utf-8")).hex()
        alert_file_path.unlink()
        create_alert_file(alert_file_path, master_sk, "This is test preimage!")

        await time_out_assert(15, check_genesis, True, expected_genesis)
