import os

from pathlib import Path
from typing import Dict, Optional


class PeerStoreResolver:
    def __init__(
        self,
        root_path: Path,
        config: Dict,
        *,
        selected_network: str,
        peers_file_path_key: str,
        legacy_peer_db_path_key: str,
        default_peers_file_path: str,
    ):
        self.root_path = root_path
        self.config = config
        self.selected_network = selected_network
        self.peers_file_path_key = peers_file_path_key
        self.legacy_peer_db_path_key = legacy_peer_db_path_key
        self.default_peers_file_path = default_peers_file_path

    def _resolve_and_update_config(self) -> Path:
        """
        Resolve the peers data file path from the config, and update the config if necessary.
        We leave the legacy peer db path in the config to support downgrading.

        If peers_file_path_key is not found in the config, we'll attempt to derive the path
        from the the config's legacy_peer_db_path_key value.
        """
        peers_file_path_str: Optional[str] = self.config.get(self.peers_file_path_key)
        if peers_file_path_str is None:
            # Check if the legacy peer db path exists and derive a new path from it
            peer_db_path: Optional[str] = self.config.get(self.legacy_peer_db_path_key)
            if peer_db_path is not None:
                # Use the legacy path's directory with the new peers data filename
                peers_file_path_str = os.fspath(Path(peer_db_path).parent / self._peers_file_name)
            else:
                # Neither value is present in the config, use the default
                peers_file_path_str = os.fspath(Path(self.default_peers_file_path).parent / self._peers_file_name)

            # Update the config
            self.config[self.peers_file_path_key] = peers_file_path_str
        return self.root_path / Path(peers_file_path_str)

    @property
    def _peers_file_name(self) -> str:
        if self.selected_network == "mainnet":
            return Path(self.default_peers_file_path).name
        else:
            path = Path(self.default_peers_file_path)
            return path.with_name(f"{path.stem}_{self.selected_network}{path.suffix}").name

    @property
    def peers_file_path(self) -> Path:
        return self._resolve_and_update_config()
