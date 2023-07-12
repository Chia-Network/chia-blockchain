from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from chia.util.config import create_default_chia_config
from tests.cmds.cmd_test_utils import GlobalTestRpcClients, create_service_and_wallet_client_generators


@pytest.fixture(scope="module")  # every file has its own config generated, just to be safe
def get_global_cli_clients() -> GlobalTestRpcClients:
    # we cant use the normal config fixture because it only supports function scope.
    with tempfile.TemporaryDirectory() as tmp_path:
        root_path: Path = Path(tmp_path) / "chia_root"
        root_path.mkdir(parents=True, exist_ok=True)
        create_default_chia_config(root_path)
        # ^ this is basically the generate config fixture.
        global_test_rpc_clients = GlobalTestRpcClients()
        create_service_and_wallet_client_generators(global_test_rpc_clients)
        return global_test_rpc_clients
