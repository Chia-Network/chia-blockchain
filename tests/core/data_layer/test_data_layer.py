from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, cast

import pytest

from chia.data_layer.data_layer import DataLayer
from chia.rpc.wallet_rpc_client import WalletRpcClient


async def create_sufficient_wallet_rpc_client() -> WalletRpcClient:
    return cast(WalletRpcClient, SufficientWalletRpcClient())


class SufficientWalletRpcClient:
    def close(self) -> None:
        return

    async def await_closed(self) -> None:
        return


@pytest.mark.parametrize(argnames="enable", argvalues=[True, False], ids=["log", "do not log"])
@pytest.mark.asyncio
async def test_sql_logs(enable: bool, config: Dict[str, Any], tmp_chia_root: Path) -> None:
    config["data_layer"]["log_sqlite_cmds"] = enable

    log_path = tmp_chia_root.joinpath("log", "data_sql.log")

    data_layer = DataLayer(
        config=config["data_layer"],
        root_path=tmp_chia_root,
        wallet_rpc_init=create_sufficient_wallet_rpc_client(),
        downloaders=[],
        uploaders=[],
    )
    try:
        assert not log_path.exists()
        await data_layer._start()
    finally:
        data_layer._close()
        await data_layer._await_closed()

    if enable:
        assert log_path.is_file()
    else:
        assert not log_path.exists()
