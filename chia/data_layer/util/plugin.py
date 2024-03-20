from __future__ import annotations

import json
from pathlib import Path
from typing import List

from chia.data_layer.data_layer_util import PluginRemote


async def load_plugin_configurations(root_path: Path, config_type: str) -> List[PluginRemote]:
    """
    Loads plugin configurations from the specified directory and validates that the contents
    are in the expected JSON format (an array of PluginRemote objects). It gracefully handles errors
    and ensures that the necessary directories exist, creating them if they do not.

    Args:
        root_path (Path): The root path where the plugins directory is located.
        config_type (str): The type of plugins to load ('downloaders' or 'uploaders').

    Returns:
        List[PluginRemote]: A list of valid PluginRemote instances for the specified plugin type.
    """
    config_path = root_path / "plugins" / config_type
    config_path.mkdir(parents=True, exist_ok=True)  # Ensure the config directory exists

    valid_configs = []
    for conf_file in config_path.glob("*.conf"):
        try:
            with open(conf_file) as file:
                data = json.load(file)
            # Validate that data is a list of dicts with 'url' as a key
            if isinstance(data, list) and all(isinstance(item, dict) and "url" in item for item in data):
                valid_configs.extend([PluginRemote.unmarshal(marshalled=item) for item in data])
                print(f"Valid configurations in {conf_file.name}: {data}")
        except (OSError, json.JSONDecodeError, Exception) as e:
            print(f"Error loading or parsing {conf_file}: {e}, skipping this file.")
    return valid_configs
