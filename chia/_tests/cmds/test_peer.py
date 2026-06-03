from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import pytest
from chia_rs.sized_bytes import bytes32
from click.testing import CliRunner

from chia._tests.cmds.cmd_test_utils import TestFullNodeRpcClient, TestRpcClients, logType, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import get_bytes32
from chia.cmds import peer_funcs
from chia.cmds.chia import cli
from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.cmds_util import get_any_service_client
from chia.protocols.outbound_message import NodeType
from chia.solver.solver_rpc_client import SolverRpcClient
from chia.util.config import load_config


@dataclass
class PeerFullNodeRpcClient(TestFullNodeRpcClient):
    async def get_connections(self, node_type: NodeType | None = None) -> list[dict[str, str | int | float | bytes32]]:
        self.add_to_log("get_connections", (node_type,))
        return [
            {
                "bytes_read": 10000,
                "bytes_written": 100,
                "creation_time": 169140000.0,
                "last_message_time": 169141001.0,
                "local_port": 19411,
                "node_id": get_bytes32(1),
                "peer_host": "127.0.0.1",
                "peer_port": 47482,
                "peer_server_port": 47482,
                "type": NodeType.FULL_NODE.value,
                "peak_height": 42,
                "peak_hash": "0x" + get_bytes32(2).hex(),
            }
        ]


@pytest.mark.parametrize("service_name", ["base", "Bob", "Sue"])
def test_peer_rejects_unknown_service(service_name: str, root_path_populated_with_config: Path) -> None:
    runner = CliRunner()
    context = ChiaCliContext(root_path=root_path_populated_with_config)

    result = runner.invoke(
        cli,
        ["--root-path", str(root_path_populated_with_config), "peer", service_name, "-c"],
        obj=context.to_click(),
    )

    assert result.exit_code == 2
    assert f"'{service_name}' is not one of" in result.output


def test_peer_show_connections(capsys: object, get_test_cli_clients: tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients
    test_rpc_clients.full_node_rpc_client = PeerFullNodeRpcClient()
    run_cli_command_and_assert(
        capsys,
        root_dir,
        ["peer", "full_node", "-c"],
        [
            "Connections:",
            "FULL_NODE 127.0.0.1",
            "47482/47482",
        ],
    )
    expected_calls: logType = {"get_connections": [(None,)]}
    test_rpc_clients.full_node_rpc_client.check_log(expected_calls)


@pytest.mark.anyio
async def test_get_any_service_client_missing_config_section(
    root_path_populated_with_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(root_path_populated_with_config, "config.yaml")
    del config["solver"]

    with monkeypatch.context() as m:
        m.setattr("chia.cmds.cmds_util.load_config", lambda *_args, **_kwargs: config)

        with pytest.raises(click.UsageError, match=re.escape("Service 'solver' is not configured in config.yaml")):
            await get_any_service_client(SolverRpcClient, root_path_populated_with_config).__aenter__()


@pytest.mark.anyio
async def test_peer_show_connections_missing_config_section(
    root_path_populated_with_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(root_path_populated_with_config, "config.yaml")
    del config["solver"]

    class FakeRpcClient:
        pass

    @asynccontextmanager
    async def fake_get_any_service_client(
        client_type: type,
        root_path: Path,
        rpc_port: int | None = None,
        consume_errors: bool = True,
        use_ssl: bool = True,
    ) -> AsyncIterator[tuple[FakeRpcClient, dict[str, Any]]]:
        del client_type, root_path, consume_errors, use_ssl
        yield FakeRpcClient(), config

    with monkeypatch.context() as m:
        m.setattr(peer_funcs, "get_any_service_client", fake_get_any_service_client)

        with pytest.raises(click.UsageError, match=re.escape("Service 'solver' is not configured in config.yaml")):
            await peer_funcs.peer_async(
                "solver",
                8667,
                root_path_populated_with_config,
                show_connections=True,
                add_connection="",
                remove_connection="",
            )
