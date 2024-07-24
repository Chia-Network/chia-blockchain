from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from chia.data_layer.data_layer_util import PluginRemote
from chia.data_layer.util.plugin import load_plugin_configurations

log = logging.getLogger(__name__)


@pytest.mark.anyio
async def test_load_plugin_configurations(tmp_path: Path) -> None:
    # Setup test environment
    plugin_type = "downloaders"
    root_path = tmp_path / "plugins_root"
    config_path = root_path / "plugins" / plugin_type
    config_path.mkdir(parents=True)

    # Create valid and invalid config files
    valid_config = [
        {"url": "https://example.com/plugin1"},
        {"url": "https://example.com/plugin2", "headers": {"Authorization": "Bearer token"}},
    ]
    invalid_config = {"config": "invalid"}
    with open(config_path / "valid.conf", "w") as file:
        json.dump(valid_config, file)
    with open(config_path / "invalid.conf", "w") as file:
        json.dump(invalid_config, file)

    # Test loading configurations
    loaded_configs = await load_plugin_configurations(root_path, plugin_type, log)

    expected_configs = [
        PluginRemote.unmarshal(marshalled=config) if isinstance(config, dict) else None for config in valid_config
    ]
    # Filter out None values that may have been added due to invalid config structures
    expected_configs = list(filter(None, expected_configs))
    assert set(loaded_configs) == set(expected_configs), "Should only load valid configurations"


@pytest.mark.anyio
async def test_load_plugin_configurations_no_configs(tmp_path: Path) -> None:
    # Setup test environment with no config files
    plugin_type = "uploaders"
    root_path = tmp_path / "plugins_root"

    # Test loading configurations with no config files
    loaded_configs = await load_plugin_configurations(root_path, plugin_type, log)

    assert loaded_configs == [], "Should return an empty list when no configurations are present"


@pytest.mark.anyio
async def test_load_plugin_configurations_unreadable_file(tmp_path: Path) -> None:
    # Setup test environment
    plugin_type = "downloaders"
    root_path = tmp_path / "plugins_root"
    config_path = root_path / "plugins" / plugin_type
    config_path.mkdir(parents=True)

    # Create an unreadable config file
    unreadable_config_file = config_path / "unreadable.conf"
    unreadable_config_file.touch()
    unreadable_config_file.chmod(0)  # Make the file unreadable

    # Test loading configurations
    loaded_configs = await load_plugin_configurations(root_path, plugin_type, log)

    assert loaded_configs == [], "Should gracefully handle unreadable files"


@pytest.mark.anyio
async def test_load_plugin_configurations_improper_json(tmp_path: Path) -> None:
    # Setup test environment
    plugin_type = "downloaders"
    root_path = tmp_path / "plugins_root"
    config_path = root_path / "plugins" / plugin_type
    config_path.mkdir(parents=True)

    # Create a config file with improper JSON
    with open(config_path / "improper_json.conf", "w") as file:
        file.write("{not: 'a valid json'}")

    # Test loading configurations
    loaded_configs = await load_plugin_configurations(root_path, plugin_type, log)

    assert loaded_configs == [], "Should gracefully handle files with improper JSON"
