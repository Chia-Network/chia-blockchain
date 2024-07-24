from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import yaml

from chia.data_layer.data_layer_util import PluginRemote
from chia.util.log_exceptions import log_exceptions


async def load_plugin_configurations(root_path: Path, config_type: str, log: logging.Logger) -> List[PluginRemote]:
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
        with log_exceptions(
            log=log,
            consume=True,
            message=f"Skipping config file due to failure loading or parsing: {conf_file}",
        ):
            with open(conf_file) as file:
                data = yaml.safe_load(file)

            valid_configs.extend([PluginRemote.unmarshal(marshalled=item) for item in data])
            log.info(f"loaded plugin configuration: {conf_file}")
    return valid_configs
