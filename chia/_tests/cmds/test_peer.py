from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from chia.cmds import peer_funcs
from chia.cmds.chia import cli
from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.cmds_util import get_any_service_client
from chia.solver.solver_rpc_client import SolverRpcClient
from chia.util.config import load_config


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
            async with get_any_service_client(SolverRpcClient, root_path_populated_with_config):
                pass


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
