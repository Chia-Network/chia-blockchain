from __future__ import annotations

from logging import Logger
from typing import Tuple

import pytest

from chia.full_node.full_node_api import FullNodeAPI
from chia.server.node_discovery import FullNodeDiscovery
from chia.server.peer_store_resolver import PeerStoreResolver
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.util.default_root import SIMULATOR_ROOT_PATH


@pytest.mark.anyio
async def test_enable_private_networks(
    two_nodes: Tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
) -> None:
    chia_server = two_nodes[2]

    # Missing `enable_private_networks` config entry in introducer_peer should default to False for back compat
    discovery0 = FullNodeDiscovery(
        chia_server,
        0,
        PeerStoreResolver(
            SIMULATOR_ROOT_PATH,
            chia_server.config,
            selected_network=chia_server.config["selected_network"],
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="db/peer_table_node.sqlite",
            default_peers_file_path="db/peers.dat",
        ),
        {"host": "introducer.chia.net", "port": 8444},
        [],
        0,
        chia_server.config["selected_network"],
        None,
        Logger("node_discovery_tests"),
    )
    assert discovery0 is not None
    assert discovery0.enable_private_networks is False
    await discovery0.initialize_address_manager()
    assert discovery0.address_manager is not None
    assert discovery0.address_manager.allow_private_subnets is False

    # Test with enable_private_networks set to False in Config
    discovery1 = FullNodeDiscovery(
        chia_server,
        0,
        PeerStoreResolver(
            SIMULATOR_ROOT_PATH,
            chia_server.config,
            selected_network=chia_server.config["selected_network"],
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="db/peer_table_node.sqlite",
            default_peers_file_path="db/peers.dat",
        ),
        {"host": "introducer.chia.net", "port": 8444, "enable_private_networks": False},
        [],
        0,
        chia_server.config["selected_network"],
        None,
        Logger("node_discovery_tests"),
    )
    assert discovery1 is not None
    assert discovery1.enable_private_networks is False
    await discovery1.initialize_address_manager()
    assert discovery1.address_manager is not None
    assert discovery1.address_manager.allow_private_subnets is False

    # Test with enable_private_networks set to True in Config
    discovery2 = FullNodeDiscovery(
        chia_server,
        0,
        PeerStoreResolver(
            SIMULATOR_ROOT_PATH,
            chia_server.config,
            selected_network=chia_server.config["selected_network"],
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="db/peer_table_node.sqlite",
            default_peers_file_path="db/peers.dat",
        ),
        {"host": "introducer.chia.net", "port": 8444, "enable_private_networks": True},
        [],
        0,
        chia_server.config["selected_network"],
        None,
        Logger("node_discovery_tests"),
    )
    assert discovery2 is not None
    assert discovery2.enable_private_networks is True
    await discovery2.initialize_address_manager()
    assert discovery2.address_manager is not None
    assert discovery2.address_manager.allow_private_subnets is True
