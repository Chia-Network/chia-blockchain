from __future__ import annotations

import textwrap
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Sequence

import click
import pytest
from click.testing import CliRunner

from chia._tests.conftest import ConsensusMode
from chia._tests.environments.wallet import WalletTestFramework
from chia._tests.wallet.conftest import *  # noqa
from chia.cmds.cmd_classes import ChiaCommand, Context, NeedsWalletRPC, chia_command, option
from chia.types.blockchain_format.sized_bytes import bytes32


def check_click_parsing(cmd: ChiaCommand, *args: str) -> None:
    @click.group()
    def _cmd() -> None:
        pass

    mock_type = type(cmd.__class__.__name__, (cmd.__class__,), {})

    def dict_compare_with_ignore_context(one: Dict[str, Any], two: Dict[str, Any]) -> None:
        for k, v in one.items():
            if k == "context":
                continue
            elif isinstance(v, dict):
                dict_compare_with_ignore_context(v, two[k])
            else:
                assert v == two[k]

    def new_run(self: Any) -> None:
        # cmd is appropriately not recognized as a dataclass but I'm not sure how to hint that something is a dataclass
        dict_compare_with_ignore_context(asdict(cmd), asdict(self))  # type: ignore[call-overload]

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
    assert result.output == textwrap.dedent(
        """\
        Usage: cmd [OPTIONS] COMMAND [ARGS]...

        Options:
          --help  Show this message and exit.

        Commands:
          temp_cmd        blah
          temp_cmd_async  blah
        """
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
    class TempCMD:
        context: Context

        def run(self) -> None:
            assert self.context["foo"] == "bar"

    runner = CliRunner()
    result = runner.invoke(
        cmd,
        ["temp_cmd"],
        catch_exceptions=False,
    )
    assert result.output == ""

    # Test that other variables named context are disallowed
    with pytest.raises(ValueError, match="context"):

        @chia_command(cmd, "shouldnt_work", "blah")
        class BadCMD:
            context: int

            def run(self) -> None: ...


def test_typing() -> None:
    @click.group()
    def cmd() -> None:
        pass

    @chia_command(cmd, "temp_cmd", "blah")
    class TempCMD:
        integer: int = option("--integer", default=1, required=False)
        text: str = option("--text", default="1", required=False)
        boolean: bool = option("--boolean", default=True, required=False)
        floating_point: float = option("--floating-point", default=1.1, required=False)
        blob: bytes = option("--blob", default=b"foo", required=False)
        blob32: bytes32 = option("--blob32", default=bytes32([1] * 32), required=False)
        choice: str = option("--choice", default="a", type=click.Choice(["a", "b"]), required=False)

        def run(self) -> None: ...

    check_click_parsing(TempCMD())
    check_click_parsing(
        TempCMD(),
        "--integer",
        "1",
        "--text",
        "1",
        "--boolean",
        "true",
        "--floating-point",
        "1.1",
        "--blob",
        "0x666f6f",
        "--blob32",
        "0x0101010101010101010101010101010101010101010101010101010101010101",
        "--choice",
        "a",
    )

    # Test optional
    @chia_command(cmd, "temp_cmd_optional", "blah")
    class TempCMDOptional:
        optional: Optional[int] = option("--optional", required=False)

        def run(self) -> None: ...

    check_click_parsing(TempCMDOptional(optional=None))
    check_click_parsing(TempCMDOptional(optional=1), "--optional", "1")

    # Test optional failure
    with pytest.raises(TypeError):

        @chia_command(cmd, "temp_cmd_optional_bad", "blah")
        class TempCMDOptionalBad2:
            optional: Optional[int] = option("--optional", required=True)

            def run(self) -> None: ...

    with pytest.raises(TypeError):

        @chia_command(cmd, "temp_cmd_optional_bad", "blah")
        class TempCMDOptionalBad3:
            optional: Optional[int] = option("--optional", default="string", required=False)

            def run(self) -> None: ...

    @chia_command(cmd, "temp_cmd_optional_fine", "blah")
    class TempCMDOptionalBad4:
        optional: Optional[int] = option("--optional", default=None, required=False)

        def run(self) -> None: ...

    # Test multiple
    @chia_command(cmd, "temp_cmd_sequence", "blah")
    class TempCMDSequence:
        sequence: Sequence[int] = option("--sequence", multiple=True)

        def run(self) -> None: ...

    check_click_parsing(TempCMDSequence(sequence=tuple()))
    check_click_parsing(TempCMDSequence(sequence=(1, 2)), "--sequence", "1", "--sequence", "2")

    # Test sequence failure
    with pytest.raises(TypeError):

        @chia_command(cmd, "temp_cmd_sequence_bad", "blah")
        class TempCMDSequenceBad:
            sequence: Sequence[int] = option("--sequence")

            def run(self) -> None: ...

    with pytest.raises(TypeError):

        @chia_command(cmd, "temp_cmd_sequence_bad", "blah")
        class TempCMDSequenceBad2:
            sequence: int = option("--sequence", multiple=True)

            def run(self) -> None: ...

    with pytest.raises(ValueError):

        @chia_command(cmd, "temp_cmd_sequence_bad", "blah")
        class TempCMDSequenceBad3:
            sequence: Sequence[int] = option("--sequence", default=[1, 2, 3], multiple=True)

            def run(self) -> None: ...

    with pytest.raises(TypeError):

        @chia_command(cmd, "temp_cmd_sequence_bad", "blah")
        class TempCMDSequenceBad4:
            sequence: Sequence[int] = option("--sequence", default=(1, 2, "3"), multiple=True)

            def run(self) -> None: ...

    # Test invalid type
    with pytest.raises(TypeError):

        @chia_command(cmd, "temp_cmd_bad_type", "blah")
        class TempCMDBadType:
            sequence: List[int] = option("--sequence")

            def run(self) -> None: ...

    # Test invalid default
    with pytest.raises(TypeError):

        @chia_command(cmd, "temp_cmd_bad_default", "blah")
        class TempCMDBadDefault:
            integer: int = option("--int", default="string")

            def run(self) -> None: ...

    # Test bytes parsing
    @chia_command(cmd, "temp_cmd_bad_bytes", "blah")
    class TempCMDBadBytes:
        blob: bytes = option("--blob", required=True)

        def run(self) -> None: ...

    @chia_command(cmd, "temp_cmd_bad_bytes32", "blah")
    class TempCMDBadBytes32:
        blob32: bytes32 = option("--blob32", required=True)

        def run(self) -> None: ...

    runner = CliRunner()
    result = runner.invoke(
        cmd,
        ["temp_cmd_bad_bytes", "--blob", "not a blob"],
        catch_exceptions=False,
    )
    assert "not a valid hex string" in result.output

    result = runner.invoke(
        cmd,
        ["temp_cmd_bad_bytes32", "--blob32", "0xdeadbeef"],
        catch_exceptions=False,
    )
    assert "not a valid 32-byte hex string" in result.output


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
    class TempCMD:
        rpc_info: NeedsWalletRPC

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
        rpc_info=NeedsWalletRPC(
            context={"root_path": wallet_environments.environments[0].node.root_path},
            wallet_rpc_port=port,
            fingerprint=fingerprint,
        ),
    )
    check_click_parsing(expected_command, "-wp", str(port), "-f", str(fingerprint))

    async with expected_command.rpc_info.wallet_rpc(consume_errors=False) as client_info:
        assert await client_info.client.get_logged_in_fingerprint() == fingerprint

    # We don't care about setting the correct arg type here
    test_present_client_info = TempCMD(rpc_info=NeedsWalletRPC(client_info="hello world"))  # type: ignore[arg-type]
    async with test_present_client_info.rpc_info.wallet_rpc(consume_errors=False) as client_info:
        assert client_info == "hello world"  # type: ignore[comparison-overlap]
