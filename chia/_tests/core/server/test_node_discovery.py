from __future__ import annotations

from logging import Logger
from pathlib import Path

import pytest

from chia.full_node.full_node_api import FullNodeAPI
from chia.server.node_discovery import FullNodeDiscovery
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.util.default_root import SIMULATOR_ROOT_PATH


@pytest.mark.anyio
async def test_enable_private_networks(
    two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
) -> None:
    chia_server = two_nodes[2]

    # Missing `enable_private_networks` config entry in introducer_peer should default to False for back compat
    discovery0 = FullNodeDiscovery(
        server=chia_server,
        target_outbound_count=0,
        peers_file_path=SIMULATOR_ROOT_PATH / Path(chia_server.config["peers_file_path"]),
        introducer_info={"host": "introducer.chia.net", "port": 8444},
        dns_servers=[],
        peer_connect_interval=0,
        selected_network=chia_server.config["selected_network"],
        default_port=None,
        log=Logger("node_discovery_tests"),
    )
    assert discovery0 is not None
    assert discovery0.enable_private_networks is False
    await discovery0.initialize_address_manager()
    assert discovery0.address_manager is not None
    assert discovery0.address_manager.allow_private_subnets is False

    # Missing `default_port` but known selected_network should automatically pick a port
    discovery0 = FullNodeDiscovery(
        server=chia_server,
        target_outbound_count=0,
        peers_file_path=SIMULATOR_ROOT_PATH / Path(chia_server.config["peers_file_path"]),
        introducer_info={"host": "introducer.chia.net", "port": 8444},
        dns_servers=[],
        peer_connect_interval=0,
        selected_network="testnet7",
        default_port=None,
        log=Logger("node_discovery_tests"),
    )
    assert discovery0.default_port == 58444

    # Test with enable_private_networks set to False in Config
    discovery1 = FullNodeDiscovery(
        server=chia_server,
        target_outbound_count=0,
        peers_file_path=SIMULATOR_ROOT_PATH / Path(chia_server.config["peers_file_path"]),
        introducer_info={"host": "introducer.chia.net", "port": 8444, "enable_private_networks": False},
        dns_servers=[],
        peer_connect_interval=0,
        selected_network=chia_server.config["selected_network"],
        default_port=None,
        log=Logger("node_discovery_tests"),
    )
    assert discovery1 is not None
    assert discovery1.enable_private_networks is False
    await discovery1.initialize_address_manager()
    assert discovery1.address_manager is not None
    assert discovery1.address_manager.allow_private_subnets is False

    # Test with enable_private_networks set to True in Config
    discovery2 = FullNodeDiscovery(
        server=chia_server,
        target_outbound_count=0,
        peers_file_path=SIMULATOR_ROOT_PATH / Path(chia_server.config["peers_file_path"]),
        introducer_info={"host": "introducer.chia.net", "port": 8444, "enable_private_networks": True},
        dns_servers=[],
        peer_connect_interval=0,
        selected_network=chia_server.config["selected_network"],
        default_port=None,
        log=Logger("node_discovery_tests"),
    )
    assert discovery2 is not None
    assert discovery2.enable_private_networks is True
    await discovery2.initialize_address_manager()
    assert discovery2.address_manager is not None
    assert discovery2.address_manager.allow_private_subnets is True
