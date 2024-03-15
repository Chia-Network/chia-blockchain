from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterator, Tuple

import pytest

from chia._tests.cmds.cmd_test_utils import TestRpcClients, create_service_and_wallet_client_generators
from chia.util.config import create_default_chia_config


@pytest.fixture(scope="module")  # every file has its own config generated, just to be safe
def get_test_cli_clients() -> Iterator[Tuple[TestRpcClients, Path]]:
    # we cant use the normal config fixture because it only supports function scope.
    with tempfile.TemporaryDirectory() as tmp_path:
        root_path: Path = Path(tmp_path) / "chia_root"
        root_path.mkdir(parents=True, exist_ok=True)
        create_default_chia_config(root_path)
        # ^ this is basically the generate config fixture.
        global_test_rpc_clients = TestRpcClients()
        create_service_and_wallet_client_generators(global_test_rpc_clients, root_path)
        yield global_test_rpc_clients, root_path
