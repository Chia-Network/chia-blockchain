from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from chia.server.peer_store_resolver import PeerStoreResolver


class TestPeerStoreResolver:
    # use tmp_path pytest fixture to create a temporary directory
    def test_resolve_unmodified_legacy_peer_db_path(self, tmp_path: Path):
        """
        When the config only has the legacy "peer_db_path" key set, the resolver should
        derive the peers_file_path from the legacy db's path.
        """

        root_path: Path = tmp_path
        config: Dict[str, str] = {"peer_db_path": "db/peer_table_node.sqlite"}
        resolver: PeerStoreResolver = PeerStoreResolver(
            root_path,
            config,
            selected_network="mainnet",
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="peer_db_path",
            default_peers_file_path="db/peers.dat",
        )
        # Expect: peers.dat path has the same directory as the legacy db
        assert resolver.peers_file_path == root_path / Path("db/peers.dat")
        # Expect: the config is updated with the new value
        assert config["peers_file_path"] == os.fspath(Path("db/peers.dat"))
        # Expect: the config retains the legacy peer_db_path value
        assert config["peer_db_path"] == "db/peer_table_node.sqlite"

    # use tmp_path pytest fixture to create a temporary directory
    def test_resolve_modified_legacy_peer_db_path(self, tmp_path: Path):
        """
        When the config has a user-modified value for the legacy "peer_db_path" key, the
        resolver should derive the peers_file_path from the legacy db's path.
        """

        root_path: Path = tmp_path
        config: Dict[str, str] = {"peer_db_path": "some/modified/db/path/peer_table_node.sqlite"}
        resolver: PeerStoreResolver = PeerStoreResolver(
            root_path,
            config,
            selected_network="mainnet",
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="peer_db_path",
            default_peers_file_path="db/peers.dat",
        )
        # Expect: peers.dat path has the same directory as the legacy db
        assert resolver.peers_file_path == root_path / Path("some/modified/db/path/peers.dat")
        # Expect: the config is updated with the new value
        assert config["peers_file_path"] == os.fspath(Path("some/modified/db/path/peers.dat"))
        # Expect: the config retains the legacy peer_db_path value
        assert config["peer_db_path"] == "some/modified/db/path/peer_table_node.sqlite"

    # use tmp_path pytest fixture to create a temporary directory
    def test_resolve_default_peers_file_path(self, tmp_path: Path):
        """
        When the config has a value for the peers_file_path key, the resolver should
        use that value.
        """

        root_path: Path = tmp_path
        config: Dict[str, str] = {"peers_file_path": "db/peers.dat"}
        resolver: PeerStoreResolver = PeerStoreResolver(
            root_path,
            config,
            selected_network="mainnet",
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="peer_db_path",
            default_peers_file_path="db/peers.dat",
        )
        # Expect: peers.dat path is the same as the location specified in the config
        assert resolver.peers_file_path == root_path / Path("db/peers.dat")
        # Expect: the config is updated with the new value
        assert config["peers_file_path"] == "db/peers.dat"
        # Expect: the config doesn't add a legacy peer_db_path value
        assert config.get("peer_db_path") is None

    # use tmp_path pytest fixture to create a temporary directory
    def test_resolve_modified_peers_file_path(self, tmp_path: Path):
        """
        When the config has a modified value for the peers_file_path key, the resolver
        should use that value.
        """

        root_path: Path = tmp_path
        config: Dict[str, str] = {"peers_file_path": "some/modified/db/path/peers.dat"}
        resolver: PeerStoreResolver = PeerStoreResolver(
            root_path,
            config,
            selected_network="mainnet",
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="peer_db_path",
            default_peers_file_path="db/peers.dat",
        )
        # Expect: peers.dat path is the same as the location specified in the config
        assert resolver.peers_file_path == root_path / Path("some/modified/db/path/peers.dat")
        # Expect: the config is updated with the new value
        assert config["peers_file_path"] == "some/modified/db/path/peers.dat"
        # Expect: the config doesn't add a legacy peer_db_path value
        assert config.get("peer_db_path") is None

    def test_resolve_both_peers_file_path_and_legacy_peer_db_path_exist(self, tmp_path: Path):
        """
        When the config has values for both the legacy peer_db_path and peer_files_path, the
        peers_file_path value should take precedence.
        """

        root_path: Path = tmp_path
        config: Dict[str, str] = {
            "peer_db_path": "db/peer_table_node.sqlite",
            "peers_file_path": "db/peers.dat",
        }
        resolver: PeerStoreResolver = PeerStoreResolver(
            root_path,
            config,
            selected_network="mainnet",
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="peer_db_path",
            default_peers_file_path="db/peers.dat",
        )
        # Expect: peers.dat path is the same as the location specified in the config
        assert resolver.peers_file_path == root_path / Path("db/peers.dat")
        # Expect: the config is updated with the new value
        assert config["peers_file_path"] == "db/peers.dat"
        # Expect: the config retains the legacy peer_db_path value
        assert config["peer_db_path"] == "db/peer_table_node.sqlite"

    def test_resolve_modified_both_peers_file_path_and_legacy_peer_db_path_exist(self, tmp_path: Path):
        """
        When the config has modified values for both the peers_file_path and legacy peer_db_path,
        the resolver should use the peers_file_path value.
        """

        root_path: Path = tmp_path
        config: Dict[str, str] = {
            "peer_db_path": "some/modified/db/path/peer_table_node.sqlite",
            "peers_file_path": "some/modified/db/path/peers.dat",
        }
        resolver: PeerStoreResolver = PeerStoreResolver(
            root_path,
            config,
            selected_network="mainnet",
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="peer_db_path",
            default_peers_file_path="db/peers.dat",
        )
        # Expect: peers.dat path is the same as the location specified in the config
        assert resolver.peers_file_path == root_path / Path("some/modified/db/path/peers.dat")
        # Expect: the config is updated with the new value
        assert config["peers_file_path"] == "some/modified/db/path/peers.dat"
        # Expect: the config retains the legacy peer_db_path value
        assert config["peer_db_path"] == "some/modified/db/path/peer_table_node.sqlite"

    # use tmp_path pytest fixture to create a temporary directory
    def test_resolve_missing_keys(self, tmp_path: Path):
        """
        When the config is missing both peer_db_path and peers_file_path keys, the resolver
        should use the default value for peers_file_path.
        """

        root_path: Path = tmp_path
        config: Dict[str, str] = {}
        resolver: PeerStoreResolver = PeerStoreResolver(
            root_path,
            config,
            selected_network="mainnet",
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="peer_db_path",
            default_peers_file_path="db/peers.dat",
        )
        # Expect: peers.dat Path is set to the default location
        assert resolver.peers_file_path == root_path / Path("db/peers.dat")
        # Expect: the config is updated with the new value
        assert config["peers_file_path"] == os.fspath(Path("db/peers.dat"))
        # Expect: the config doesn't add a legacy peer_db_path value
        assert config.get("peer_db_path") is None

    # use tmp_path pytest fixture to create a temporary directory
    def test_resolve_with_testnet(self, tmp_path: Path):
        """
        When the selected network is testnet, the resolved path's filename should
        include 'testnet' in the name.
        """

        root_path: Path = tmp_path
        config: Dict[str, str] = {}
        resolver: PeerStoreResolver = PeerStoreResolver(
            root_path,
            config,
            selected_network="testnet123",
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="peer_db_path",
            default_peers_file_path="db/peers.dat",
        )
        # Expect: resolved file path has testnet in the name
        assert resolver.peers_file_path == root_path / Path("db/peers_testnet123.dat")
        # Expect: the config is updated with the new value
        assert config["peers_file_path"] == os.fspath(Path("db/peers_testnet123.dat"))
        # Expect: the config doesn't add a legacy peer_db_path value
        assert config.get("peer_db_path") is None

    # use tmp_path pytest fixture to create a temporary directory
    def test_resolve_default_legacy_db_path(self, tmp_path: Path):
        """
        When the config has a value for the peer_db_path key, the resolver should
        use that value.
        """

        root_path: Path = tmp_path
        config: Dict[str, str] = {"peer_db_path": "db/peer_table_node.sqlite"}
        resolver: PeerStoreResolver = PeerStoreResolver(
            root_path,
            config,
            selected_network="mainnet",
            peers_file_path_key="peers_file_path",
            legacy_peer_db_path_key="peer_db_path",
            default_peers_file_path="db/peers.dat",
        )
        # Expect: peers.dat path has the same directory as the legacy db
        assert resolver.legacy_peer_db_path == root_path / Path("db/peer_table_node.sqlite")
        # Expect: the config is updated with the new value
        assert config["peer_db_path"] == "db/peer_table_node.sqlite"
