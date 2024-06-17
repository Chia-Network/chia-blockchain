from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, cast

import pytest

from chia._tests.util.misc import RecordingWebServer
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_util import PluginRemote
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32


async def create_sufficient_wallet_rpc_client() -> WalletRpcClient:
    return cast(WalletRpcClient, SufficientWalletRpcClient())


class SufficientWalletRpcClient:
    def close(self) -> None:
        return

    async def await_closed(self) -> None:
        return


@pytest.mark.parametrize(argnames="enable", argvalues=[True, False], ids=["log", "do not log"])
@pytest.mark.anyio
async def test_sql_logs(enable: bool, config: Dict[str, Any], tmp_chia_root: Path) -> None:
    config["data_layer"]["log_sqlite_cmds"] = enable

    log_path = tmp_chia_root.joinpath("log", "data_sql.log")

    data_layer = DataLayer.create(
        config=config["data_layer"],
        root_path=tmp_chia_root,
        wallet_rpc_init=create_sufficient_wallet_rpc_client(),
        downloaders=[],
        uploaders=[],
    )
    assert not log_path.exists()
    async with data_layer.manage():
        pass

    if enable:
        assert log_path.is_file()
    else:
        assert not log_path.exists()


@pytest.mark.anyio
async def test_plugin_requests_use_custom_headers(
    recording_web_server: RecordingWebServer,
    config: Dict[str, Any],
    tmp_chia_root: Path,
) -> None:
    header_key = "vbiuoqemnrlah"
    header_value = "98754718932345"

    plugin_remote = PluginRemote(
        url=recording_web_server.web_server.url(),
        headers={header_key: header_value},
    )

    async def wallet_rpc_init() -> WalletRpcClient:
        # this return is not presently used for this test
        return None  # type: ignore[return-value]

    data_layer = DataLayer.create(
        config=config["data_layer"],
        root_path=tmp_chia_root,
        wallet_rpc_init=wallet_rpc_init(),
        downloaders=[plugin_remote],
        uploaders=[plugin_remote],
    )

    async with data_layer.manage():
        await data_layer.get_downloader(store_id=bytes32([0] * 32), url="")
        await data_layer.get_uploaders(store_id=bytes32([0] * 32))
        await data_layer.check_plugins()

    header_values = {request.headers.get(header_key) for request in recording_web_server.requests}
    assert header_values == {header_value}
