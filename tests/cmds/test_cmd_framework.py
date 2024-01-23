from __future__ import annotations

from dataclasses import asdict
from typing import Any, TypeVar

import click
import pytest
from click.testing import CliRunner

from chia.cmds.cmd_classes import ChiaCommand, NeedsContext, NeedsWalletRPC, chia_command, option
from tests.conftest import ConsensusMode
from tests.environments.wallet import WalletTestFramework
from tests.wallet.conftest import *  # noqa

_T_Command = TypeVar("_T_Command", bound=ChiaCommand)


def check_click_parsing(cmd: ChiaCommand, *args: str) -> None:
    @click.group()
    def _cmd() -> None:
        pass

    mock_type = type(cmd.__class__.__name__, (cmd.__class__,), {})

    def new_run(self: Any) -> None:
        # cmd is appropriately not recognized as a dataclass but I'm not sure how to hint that something is a dataclass
        other_dict = asdict(cmd)  # type: ignore[call-overload]
        for k, v in asdict(self).items():
            if k == "context":
                continue
            assert v == other_dict[k]

    setattr(mock_type, "run", new_run)
    chia_command(_cmd, "_", "")(mock_type)

    runner = CliRunner()
    result = runner.invoke(_cmd, ["_", *args], catch_exceptions=False)
    assert result.output == ""


def test_cmd_bases() -> None:
    @click.group()
    def cmd() -> None:
        pass

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD:
        def run(self) -> None:
            print("syncronous")

    @chia_command(cmd, "temp_cmd_async", "blah")
    class TempCMDAsync:
        async def run(self) -> None:
            print("asyncronous")

    runner = CliRunner()
    result = runner.invoke(
        cmd,
        ["--help"],
        catch_exceptions=False,
    )
    assert result.output == (
        "Usage: cmd [OPTIONS] COMMAND [ARGS]...\n\nOptions:\n  --help  Show this "
        "message and exit.\n\nCommands:\n  temp_cmd        blah\n  temp_cmd_async  blah\n"
    )
    result = runner.invoke(
        cmd,
        ["temp_cmd"],
        catch_exceptions=False,
    )
    assert result.output == "syncronous\n"
    result = runner.invoke(
        cmd,
        ["temp_cmd_async"],
        catch_exceptions=False,
    )
    assert result.output == "asyncronous\n"


def test_option_loading() -> None:
    @click.group()
    def cmd() -> None:
        pass

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD:
        some_option: int = option("-o", "--some-option", required=True, type=int)

        def run(self) -> None:
            print(self.some_option)

    @chia_command(cmd, "temp_cmd_2", "blah")
    class TempCMD2:
        some_option: int = option("-o", "--some-option", required=True, type=int, default=13)

        def run(self) -> None:
            print(self.some_option)

    runner = CliRunner()
    result = runner.invoke(
        cmd,
        ["temp_cmd"],
        catch_exceptions=False,
    )
    assert "Missing option '-o' / '--some-option'" in result.output
    result = runner.invoke(
        cmd,
        [
            "temp_cmd",
            "-o",
            "13",
        ],
        catch_exceptions=False,
    )
    assert "13\n" == result.output
    result = runner.invoke(
        cmd,
        [
            "temp_cmd_2",
        ],
        catch_exceptions=False,
    )
    assert "13\n" == result.output

    assert TempCMD2() == TempCMD2(some_option=13)


def test_context_requirement() -> None:
    @click.group()
    @click.pass_context
    def cmd(ctx: click.Context) -> None:
        ctx.obj = {"foo": "bar"}

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD(NeedsContext):
        def run(self) -> None:
            assert self.context["foo"] == "bar"

    runner = CliRunner()
    result = runner.invoke(
        cmd,
        ["temp_cmd"],
        catch_exceptions=False,
    )
    assert result.output == ""


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="doesn't matter")
@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "trusted": True,
            "reuse_puzhash": False,
        }
    ],
    indirect=True,
)
@pytest.mark.anyio
async def test_wallet_rpc_helper(wallet_environments: WalletTestFramework) -> None:
    port: int = wallet_environments.environments[0].rpc_client.port

    assert wallet_environments.environments[0].node.logged_in_fingerprint is not None
    fingerprint: int = wallet_environments.environments[0].node.logged_in_fingerprint

    @click.group()
    def cmd() -> None:
        pass

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD(NeedsWalletRPC):
        def run(self) -> None:
            pass

    runner = CliRunner()
    result = runner.invoke(
        cmd,
        [
            "temp_cmd",
            "-wp",
            str(port),
            "-f",
            str(fingerprint),
        ],
        catch_exceptions=False,
    )
    assert result.output == ""

    result = runner.invoke(
        cmd,
        [
            "temp_cmd",
        ],
        catch_exceptions=False,
    )
    assert result.output == ""

    expected_command = TempCMD(
        context={"root_path": wallet_environments.environments[0].node.root_path},
        wallet_rpc_port=port,
        fingerprint=fingerprint,
    )
    check_click_parsing(expected_command, "-wp", str(port), "-f", str(fingerprint))

    async with expected_command.wallet_rpc(consume_errors=False) as client_info:
        assert await client_info.client.get_logged_in_fingerprint() == fingerprint
