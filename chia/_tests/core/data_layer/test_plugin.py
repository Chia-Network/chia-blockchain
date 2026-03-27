from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from chia_rs.sized_bytes import bytes32

from chia.data_layer.data_layer import get_plugin_info
from chia.data_layer.data_layer_util import PluginRemote, ServerInfo
from chia.data_layer.download_data import download_file
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


DUMMY_TIMEOUT = aiohttp.ClientTimeout(total=5, sock_connect=2)


def _make_mock_response(status: int = 200, json_data: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    if json_data is not None:
        resp.text = AsyncMock(return_value=json.dumps(json_data))
        resp.json = AsyncMock(return_value=json_data)
    return resp


@asynccontextmanager
async def _mock_session_post(response: MagicMock) -> AsyncIterator[MagicMock]:
    """Yields a mock that replaces aiohttp.ClientSession as an async context manager."""
    post_cm = MagicMock()
    post_cm.__aenter__ = AsyncMock(return_value=response)
    post_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post = MagicMock(return_value=post_cm)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    with patch("chia.data_layer.data_layer.aiohttp.ClientSession", return_value=session):
        yield session


@asynccontextmanager
async def _mock_session_post_download(response: MagicMock) -> AsyncIterator[MagicMock]:
    """Same as above but patches the download_data module."""
    post_cm = MagicMock()
    post_cm.__aenter__ = AsyncMock(return_value=response)
    post_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post = MagicMock(return_value=post_cm)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    with patch("chia.data_layer.download_data.aiohttp.ClientSession", return_value=session):
        yield session


@pytest.mark.anyio
async def test_get_plugin_info_timeout() -> None:
    plugin = PluginRemote(url="http://localhost:9999")

    with patch(
        "chia.data_layer.data_layer.aiohttp.ClientSession",
        side_effect=asyncio.TimeoutError("connection timed out"),
    ):
        remote, result = await get_plugin_info(plugin, DUMMY_TIMEOUT)

    assert remote is plugin
    assert "error" in result
    assert "TimeoutError" in result["error"]


@pytest.mark.anyio
async def test_get_plugin_info_client_error() -> None:
    plugin = PluginRemote(url="http://localhost:9999")

    with patch(
        "chia.data_layer.data_layer.aiohttp.ClientSession",
        side_effect=aiohttp.ClientError("connection refused"),
    ):
        remote, result = await get_plugin_info(plugin, DUMMY_TIMEOUT)

    assert remote is plugin
    assert "error" in result
    assert "ClientError" in result["error"]


@pytest.mark.anyio
async def test_get_plugin_info_success() -> None:
    plugin = PluginRemote(url="http://localhost:9999")
    plugin_response = {"name": "test-plugin", "version": "1.0"}
    response = _make_mock_response(status=200, json_data=plugin_response)

    async with _mock_session_post(response):
        remote, result = await get_plugin_info(plugin, DUMMY_TIMEOUT)

    assert remote is plugin
    assert result["status"] == 200
    assert result["response"] == plugin_response


@pytest.mark.anyio
async def test_download_file_plugin_success(tmp_path: Path) -> None:
    store_id = bytes32.zeros
    root_hash = bytes32.zeros
    server_info = ServerInfo(url="http://mirror.example.com", num_consecutive_failures=0, ignore_till=0)
    downloader = PluginRemote(url="http://localhost:9999")
    data_store = MagicMock()

    response = _make_mock_response(status=200, json_data={"downloaded": True})

    async with _mock_session_post_download(response):
        result = await download_file(
            data_store=data_store,
            target_filename_path=tmp_path / "nonexistent.dat",
            store_id=store_id,
            root_hash=root_hash,
            generation=1,
            server_info=server_info,
            proxy_url=None,
            downloader=downloader,
            timeout=DUMMY_TIMEOUT,
            client_foldername=tmp_path,
            timestamp=1000,
            log=log,
            grouped_by_store=False,
            group_downloaded_files_by_store=False,
            max_delta_file_size=10 * 1024 * 1024,  # 10 MB
        )

    assert result is True


@pytest.mark.anyio
async def test_download_file_plugin_timeout(tmp_path: Path) -> None:
    store_id = bytes32.zeros
    root_hash = bytes32.zeros
    server_info = ServerInfo(url="http://mirror.example.com", num_consecutive_failures=0, ignore_till=0)
    downloader = PluginRemote(url="http://localhost:9999")
    data_store = MagicMock()

    with patch(
        "chia.data_layer.download_data.aiohttp.ClientSession",
        side_effect=asyncio.TimeoutError("plugin timed out"),
    ):
        result = await download_file(
            data_store=data_store,
            target_filename_path=tmp_path / "nonexistent.dat",
            store_id=store_id,
            root_hash=root_hash,
            generation=1,
            server_info=server_info,
            proxy_url=None,
            downloader=downloader,
            timeout=DUMMY_TIMEOUT,
            client_foldername=tmp_path,
            timestamp=1000,
            log=log,
            grouped_by_store=False,
            group_downloaded_files_by_store=False,
            max_delta_file_size=10 * 1024 * 1024,  # 10 MB
        )

    assert result is False


@pytest.mark.anyio
async def test_download_file_plugin_client_error(tmp_path: Path) -> None:
    store_id = bytes32.zeros
    root_hash = bytes32.zeros
    server_info = ServerInfo(url="http://mirror.example.com", num_consecutive_failures=0, ignore_till=0)
    downloader = PluginRemote(url="http://localhost:9999")
    data_store = MagicMock()

    with patch(
        "chia.data_layer.download_data.aiohttp.ClientSession",
        side_effect=aiohttp.ClientError("connection refused"),
    ):
        result = await download_file(
            data_store=data_store,
            target_filename_path=tmp_path / "nonexistent.dat",
            store_id=store_id,
            root_hash=root_hash,
            generation=1,
            server_info=server_info,
            proxy_url=None,
            downloader=downloader,
            timeout=DUMMY_TIMEOUT,
            client_foldername=tmp_path,
            timestamp=1000,
            log=log,
            grouped_by_store=False,
            group_downloaded_files_by_store=False,
            max_delta_file_size=10 * 1024 * 1024,  # 10 MB
        )

    assert result is False
