from __future__ import annotations

from logging import Logger
from pathlib import Path

import pytest
from chia_rs.sized_ints import uint16, uint64

from chia.full_node.full_node_api import FullNodeAPI
from chia.server.node_discovery import FullNodeDiscovery, FullNodePeers
from chia.server.server import ChiaServer
from chia.simulator.block_tools import BlockTools
from chia.types.peer_info import PeerInfo, TimestampedPeerInfo
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


class TestPeerHostValidation:
    """Regression tests for SEC-145: unbounded peer list host strings."""

    @pytest.mark.anyio
    async def test_add_peers_common_rejects_oversized_host(
        self,
        two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    ) -> None:
        chia_server = two_nodes[2]
        discovery = FullNodeDiscovery(
            server=chia_server,
            target_outbound_count=0,
            peers_file_path=SIMULATOR_ROOT_PATH / Path(chia_server.config["peers_file_path"]),
            introducer_info={"host": "introducer.chia.net", "port": 8444, "enable_private_networks": True},
            dns_servers=[],
            peer_connect_interval=0,
            selected_network=chia_server.config["selected_network"],
            default_port=8444,
            log=Logger("test_host_validation"),
        )
        await discovery.initialize_address_manager()
        assert discovery.address_manager is not None

        oversized_host = "A" * 1000
        peer_list = [
            TimestampedPeerInfo(oversized_host, uint16(8444), uint64(0)),
        ]

        # Must not raise, and must not add the peer
        await discovery._add_peers_common(peer_list, None, False)
        assert await discovery.address_manager.size() == 0

    @pytest.mark.anyio
    async def test_add_peers_common_rejects_non_ip_host(
        self,
        two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    ) -> None:
        chia_server = two_nodes[2]
        discovery = FullNodeDiscovery(
            server=chia_server,
            target_outbound_count=0,
            peers_file_path=SIMULATOR_ROOT_PATH / Path(chia_server.config["peers_file_path"]),
            introducer_info={"host": "introducer.chia.net", "port": 8444, "enable_private_networks": True},
            dns_servers=[],
            peer_connect_interval=0,
            selected_network=chia_server.config["selected_network"],
            default_port=8444,
            log=Logger("test_host_validation"),
        )
        await discovery.initialize_address_manager()
        assert discovery.address_manager is not None

        invalid_hosts = ["not-an-ip-address", "hello world", "999.999.999.999", ""]
        peer_list = [TimestampedPeerInfo(host, uint16(8444), uint64(0)) for host in invalid_hosts]

        await discovery._add_peers_common(peer_list, None, False)
        assert await discovery.address_manager.size() == 0

    @pytest.mark.anyio
    async def test_add_peers_common_accepts_valid_ipv4(
        self,
        two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    ) -> None:
        chia_server = two_nodes[2]
        discovery = FullNodeDiscovery(
            server=chia_server,
            target_outbound_count=0,
            peers_file_path=SIMULATOR_ROOT_PATH / Path(chia_server.config["peers_file_path"]),
            introducer_info={"host": "introducer.chia.net", "port": 8444, "enable_private_networks": True},
            dns_servers=[],
            peer_connect_interval=0,
            selected_network=chia_server.config["selected_network"],
            default_port=8444,
            log=Logger("test_host_validation"),
        )
        await discovery.initialize_address_manager()
        assert discovery.address_manager is not None

        peer_list = [
            TimestampedPeerInfo("192.168.1.1", uint16(8444), uint64(0)),
        ]

        await discovery._add_peers_common(peer_list, None, False)
        assert await discovery.address_manager.size() >= 1

    @pytest.mark.anyio
    async def test_add_peers_common_mixed_valid_and_invalid(
        self,
        two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    ) -> None:
        """Invalid hosts are skipped; valid hosts in the same batch are still added."""
        chia_server = two_nodes[2]
        discovery = FullNodeDiscovery(
            server=chia_server,
            target_outbound_count=0,
            peers_file_path=SIMULATOR_ROOT_PATH / Path(chia_server.config["peers_file_path"]),
            introducer_info={"host": "introducer.chia.net", "port": 8444, "enable_private_networks": True},
            dns_servers=[],
            peer_connect_interval=0,
            selected_network=chia_server.config["selected_network"],
            default_port=8444,
            log=Logger("test_host_validation"),
        )
        await discovery.initialize_address_manager()
        assert discovery.address_manager is not None

        peer_list = [
            TimestampedPeerInfo("X" * 500, uint16(8444), uint64(0)),
            TimestampedPeerInfo("not-an-ip", uint16(8444), uint64(0)),
            TimestampedPeerInfo("192.168.1.1", uint16(8444), uint64(0)),
            TimestampedPeerInfo("192.168.1.2", uint16(8444), uint64(0)),
        ]

        await discovery._add_peers_common(peer_list, None, False)
        assert await discovery.address_manager.size() >= 1

    @pytest.mark.anyio
    async def test_add_peers_neighbour_rejects_invalid_host(
        self,
        two_nodes: tuple[FullNodeAPI, FullNodeAPI, ChiaServer, ChiaServer, BlockTools],
    ) -> None:
        chia_server = two_nodes[2]
        discovery = FullNodePeers(
            server=chia_server,
            target_outbound_count=0,
            peers_file_path=SIMULATOR_ROOT_PATH / Path(chia_server.config["peers_file_path"]),
            introducer_info={"host": "introducer.chia.net", "port": 8444, "enable_private_networks": True},
            dns_servers=[],
            peer_connect_interval=0,
            selected_network=chia_server.config["selected_network"],
            default_port=8444,
            log=Logger("test_host_validation"),
        )
        await discovery.initialize_address_manager()

        oversized_host = "B" * 500
        invalid_host = "not.an.ip"
        valid_host = "10.0.0.1"
        neighbour = PeerInfo("10.0.0.100", 8444)
        peers = [
            TimestampedPeerInfo(oversized_host, uint16(8444), uint64(0)),
            TimestampedPeerInfo(invalid_host, uint16(8444), uint64(0)),
            TimestampedPeerInfo(valid_host, uint16(8444), uint64(0)),
        ]

        await discovery.add_peers_neighbour(peers, neighbour)

        known = discovery.neighbour_known_peers.get(neighbour, set())
        assert oversized_host not in known
        assert invalid_host not in known
        assert valid_host in known
