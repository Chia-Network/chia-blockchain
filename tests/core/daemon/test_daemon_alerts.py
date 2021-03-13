import dataclasses

import pytest
from blspy import PrivateKey

from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo
from src.util.block_tools import BlockTools
from src.util.hash import std_hash
from src.util.ints import uint16
from src.util.validate_alert import create_alert_file, create_not_ready_alert_file
from tests.core.full_node.test_full_sync import node_height_at_least
from tests.setup_nodes import self_hostname, setup_daemon, setup_full_system
from tests.simulation.test_simulation import test_constants_modified
from tests.time_out_assert import time_out_assert, time_out_assert_custom_interval
from tests.util.alert_server import AlertServer

no_genesis = dataclasses.replace(test_constants_modified, GENESIS_CHALLENGE=None)
b_tools = BlockTools(constants=no_genesis)
b_tools_1 = BlockTools(constants=no_genesis)

master_int = 5399117110774477986698372024995405256382522670366369834617409486544348441851
master_sk: PrivateKey = PrivateKey.from_bytes(master_int.to_bytes(32, "big"))
pubkey_alert = bytes(master_sk.get_g1()).hex()
alert_url = "http://127.0.0.1:59000/status"

new_config = b_tools._config
new_config["CHIA_ALERTS_PUBKEY"] = pubkey_alert
new_config["ALERTS_URL"] = alert_url
new_config["daemon_port"] = 55401
new_config["network_overrides"]["constants"][new_config["selected_network"]]["GENESIS_CHALLENGE"] = None
b_tools.change_config(new_config)

new_config_1 = b_tools_1._config
new_config_1["CHIA_ALERTS_PUBKEY"] = pubkey_alert
new_config_1["ALERTS_URL"] = alert_url
new_config_1["daemon_port"] = 55402
new_config_1["network_overrides"]["constants"][new_config_1["selected_network"]]["GENESIS_CHALLENGE"] = None
b_tools_1.change_config(new_config_1)


class TestDaemonAlerts:
    @pytest.fixture(scope="function")
    async def get_daemon(self):
        async for _ in setup_daemon(btools=b_tools):
            yield _

    @pytest.fixture(scope="function")
    async def get_daemon_1(self):
        async for _ in setup_daemon(btools=b_tools_1):
            yield _

    @pytest.fixture(scope="function")
    async def simulation(self):
        async for _ in setup_full_system(b_tools_1.constants, b_tools=b_tools, b_tools_1=b_tools_1):
            yield _

    @pytest.mark.asyncio
    async def test_daemon_alert_simulation(self, simulation, get_daemon, get_daemon_1):
        node1, node2, _, _, _, _, _, _, _, server1 = simulation
        await server1.start_client(PeerInfo(self_hostname, uint16(21238)))

        daemon = get_daemon
        daemon_1 = get_daemon_1
        alert_file_path = daemon.root_path / "alert.txt"
        alert_server = await AlertServer.create_alert_server(alert_file_path, 59000)
        create_not_ready_alert_file(alert_file_path, master_sk)
        await alert_server.run()

        selected = daemon.net_config["selected_network"]

        async def num_connections():
            count = len(node2.server.connection_by_type[NodeType.FULL_NODE].items())
            return count

        await time_out_assert_custom_interval(60, 1, num_connections, 1)

        preimage = "This is test preimage!"
        expected_genesis = std_hash(bytes(preimage, "utf-8")).hex()

        alert_file_path.unlink()
        create_alert_file(alert_file_path, master_sk, "This is test preimage!")

        def check_genesis(expected):
            deamon_updated = (
                daemon.net_config["network_overrides"]["constants"][selected]["GENESIS_CHALLENGE"] == expected
            )
            deamon_1_updated = (
                daemon_1.net_config["network_overrides"]["constants"][selected]["GENESIS_CHALLENGE"] == expected
            )
            return deamon_updated and deamon_1_updated

        await time_out_assert(15, check_genesis, True, expected_genesis)

        def check_initialized():
            return node1.full_node.initialized is True and node2.full_node.initialized is True

        await time_out_assert(15, check_initialized, True)

        await time_out_assert(1500, node_height_at_least, True, node2, 7)
