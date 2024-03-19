from __future__ import annotations

import json
from pathlib import Path
from typing import List


async def load_plugin_configurations(root_path: Path, config_type: str) -> List[str]:
    """
    Loads plugin configurations from the specified directory and validates that the contents
    are in the expected JSON format (an array of strings). It gracefully handles errors and ensures
    that the necessary directories exist, creating them if they do not.

    Args:
        root_path (Path): The root path where the plugins directory is located.
        config_type (str): The type of plugins to load ('downloaders' or 'uploaders').

    Returns:
        List[str]: A list of valid configurations for the specified plugin type.
    """
    config_path = root_path / "plugins" / config_type
    # Ensure the config directory exists, create if not
    config_path.mkdir(parents=True, exist_ok=True)

    valid_configs = []
    for conf_file in config_path.glob("*.conf"):
        try:
            with open(conf_file) as file:
                data = json.load(file)
            # Validate that data is a list of strings
            if isinstance(data, list) and all(isinstance(item, str) for item in data):
                valid_configs.extend(data)
                # Print each valid configuration
                print(f"Valid configurations in {conf_file.name}: {data}")
        except (OSError, json.JSONDecodeError, Exception) as e:
            # Log or print the error based on your logging strategy
            print(f"Error loading or parsing {conf_file}: {e}, skipping this file.")
    return valid_configs
