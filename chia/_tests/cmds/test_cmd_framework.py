from __future__ import annotations

import pathlib
import textwrap
from collections.abc import Sequence
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Optional

import click
import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64
from click.testing import CliRunner

from chia._tests.environments.wallet import STANDARD_TX_ENDPOINT_ARGS, WalletTestFramework
from chia._tests.wallet.conftest import *  # noqa
from chia.cmds.cmd_classes import ChiaCliContext, ChiaCommand, chia_command, option
from chia.cmds.cmd_helpers import (
    _TRANSACTION_ENDPOINT_DECORATOR_APPLIED,
    NeedsCoinSelectionConfig,
    NeedsTXConfig,
    NeedsWalletRPC,
    TransactionEndpoint,
    TransactionEndpointWithTimelocks,
    transaction_endpoint_runner,
)
from chia.cmds.cmds_util import coin_selection_args, tx_config_args, tx_out_cmd
from chia.cmds.param_types import CliAmount
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import CoinSelectionConfig, TXConfig


def check_click_parsing(cmd: ChiaCommand, *args: str, context: Optional[ChiaCliContext] = None) -> None:
    @click.group()
    def _cmd() -> None:
        pass

    mock_type = type(cmd.__class__.__name__, (cmd.__class__,), {})

    def dict_compare_with_ignore_context(one: dict[str, Any], two: dict[str, Any]) -> None:
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

    # We hack this in because more robust solutions are harder and probably not worth it
    setattr(new_run, _TRANSACTION_ENDPOINT_DECORATOR_APPLIED, True)

    setattr(mock_type, "run", new_run)
    chia_command(group=_cmd, name="_", short_help="", help="")(mock_type)

    if context is None:
        context = ChiaCliContext()

    runner = CliRunner()
    result = runner.invoke(_cmd, ["_", *args], catch_exceptions=False, obj=context.to_click())
    assert result.output == ""


def test_cmd_bases() -> None:
    @click.group()
    def cmd() -> None:
        pass

    @chia_command(group=cmd, name="temp_cmd", short_help="blah", help="n/a")
    class TempCMD:
        def run(self) -> None:
            print("syncronous")

    @chia_command(group=cmd, name="temp_cmd_async", short_help="blah", help="n/a")
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

    @chia_command(group=cmd, name="temp_cmd", short_help="blah", help="n/a")
    class TempCMD:
        some_option: int = option("-o", "--some-option", required=True, type=int)
        choices: list[str] = option("--choice", multiple=True, type=str)

        def run(self) -> None:
            print(self.some_option)

    @chia_command(group=cmd, name="temp_cmd_2", short_help="blah", help="n/a")
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
        ctx.obj = ChiaCliContext(root_path=pathlib.Path("foo", "bar")).to_click()

    @chia_command(group=cmd, name="temp_cmd", short_help="blah", help="n/a")
    class TempCMD:
        context: ChiaCliContext

        def run(self) -> None:
            assert self.context.root_path == pathlib.Path("foo", "bar")

    runner = CliRunner()
    result = runner.invoke(
        cmd,
        ["temp_cmd"],
        catch_exceptions=False,
    )
    assert result.output == ""

    # Test that other variables named context are disallowed
    with pytest.raises(ValueError, match="context"):

        @chia_command(group=cmd, name="shouldnt_work", short_help="blah", help="n/a")
        class BadCMD:
            context: int

            def run(self) -> None: ...


def test_typing() -> None:
    @click.group()
    def cmd() -> None:
        pass

    @chia_command(group=cmd, name="temp_cmd", short_help="blah", help="n/a")
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
    @chia_command(group=cmd, name="temp_cmd_optional", short_help="blah", help="n/a")
    class TempCMDOptional:
        optional: Optional[int] = option("--optional", required=False)

        def run(self) -> None: ...

    check_click_parsing(TempCMDOptional(optional=None))
    check_click_parsing(TempCMDOptional(optional=1), "--optional", "1")

    # Test optional failure
    with pytest.raises(TypeError):

        @chia_command(group=cmd, name="temp_cmd_optional_bad", short_help="blah", help="n/a")
        class TempCMDOptionalBad2:
            optional: Optional[int] = option("--optional", required=True)

            def run(self) -> None: ...

    with pytest.raises(TypeError):

        @chia_command(group=cmd, name="temp_cmd_optional_bad", short_help="blah", help="n/a")
        class TempCMDOptionalBad3:
            optional: Optional[int] = option("--optional", default="string", required=False)

            def run(self) -> None: ...

    @chia_command(group=cmd, name="temp_cmd_optional_fine", short_help="blah", help="n/a")
    class TempCMDOptionalBad4:
        optional: Optional[int] = option("--optional", default=None, required=False)

        def run(self) -> None: ...

    # Test multiple
    @chia_command(group=cmd, name="temp_cmd_sequence", short_help="blah", help="n/a")
    class TempCMDSequence:
        sequence: Sequence[int] = option("--sequence", multiple=True)

        def run(self) -> None: ...

    check_click_parsing(TempCMDSequence(sequence=tuple()))
    check_click_parsing(TempCMDSequence(sequence=(1, 2)), "--sequence", "1", "--sequence", "2")

    # Test sequence failure
    with pytest.raises(TypeError):

        @chia_command(group=cmd, name="temp_cmd_sequence_bad", short_help="blah", help="n/a")
        class TempCMDSequenceBad:
            sequence: Sequence[int] = option("--sequence")

            def run(self) -> None: ...

    with pytest.raises(TypeError):

        @chia_command(group=cmd, name="temp_cmd_sequence_bad", short_help="blah", help="n/a")
        class TempCMDSequenceBad2:
            sequence: int = option("--sequence", multiple=True)

            def run(self) -> None: ...

    with pytest.raises(ValueError):

        @chia_command(group=cmd, name="temp_cmd_sequence_bad", short_help="blah", help="n/a")
        class TempCMDSequenceBad3:
            sequence: Sequence[int] = option("--sequence", default=[1, 2, 3], multiple=True)

            def run(self) -> None: ...

    with pytest.raises(TypeError):

        @chia_command(group=cmd, name="temp_cmd_sequence_bad", short_help="blah", help="n/a")
        class TempCMDSequenceBad4:
            sequence: Sequence[int] = option("--sequence", default=(1, 2, "3"), multiple=True)

            def run(self) -> None: ...

    # Test invalid type
    with pytest.raises(TypeError):

        @chia_command(group=cmd, name="temp_cmd_bad_type", short_help="blah", help="n/a")
        class TempCMDBadType:
            sequence: list[int] = option("--sequence")

            def run(self) -> None: ...

    # Test invalid default
    with pytest.raises(TypeError):

        @chia_command(group=cmd, name="temp_cmd_bad_default", short_help="blah", help="n/a")
        class TempCMDBadDefault:
            integer: int = option("--int", default="string")

            def run(self) -> None: ...

    # Test bytes parsing
    @chia_command(group=cmd, name="temp_cmd_bad_bytes", short_help="blah", help="n/a")
    class TempCMDBadBytes:
        blob: bytes = option("--blob", required=True)

        def run(self) -> None: ...

    @chia_command(group=cmd, name="temp_cmd_bad_bytes32", short_help="blah", help="n/a")
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


@pytest.mark.limit_consensus_modes(reason="doesn't matter")
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

    @chia_command(group=cmd, name="temp_cmd", short_help="blah", help="n/a")
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
            context=ChiaCliContext(root_path=wallet_environments.environments[0].node.root_path),
            wallet_rpc_port=port,
            fingerprint=fingerprint,
        ),
    )
    check_click_parsing(expected_command, "-wp", str(port), "-f", str(fingerprint))

    async with expected_command.rpc_info.wallet_rpc(consume_errors=False) as client_info:
        assert (await client_info.client.get_logged_in_fingerprint()).fingerprint == fingerprint

    # We don't care about setting the correct arg type here
    test_present_client_info = TempCMD(rpc_info=NeedsWalletRPC(client_info="hello world"))  # type: ignore[arg-type]
    async with test_present_client_info.rpc_info.wallet_rpc(consume_errors=False) as client_info:
        assert client_info == "hello world"  # type: ignore[comparison-overlap]


def test_tx_config_helper() -> None:
    @click.group()
    def cmd() -> None:
        pass  # pragma: no cover

    @chia_command(group=cmd, name="cs_cmd", short_help="blah", help="blah")
    class CsCMD:
        coin_selection_loader: NeedsCoinSelectionConfig

        def run(self) -> None:
            # ignoring the `None` return here for convenient testing sake
            return self.coin_selection_loader.load_coin_selection_config(100)  # type: ignore[return-value]

    example_cs_cmd = CsCMD(
        coin_selection_loader=NeedsCoinSelectionConfig(
            min_coin_amount=CliAmount(amount=Decimal("0.01"), mojos=False),
            max_coin_amount=CliAmount(amount=Decimal("0.01"), mojos=False),
            amounts_to_exclude=(CliAmount(amount=Decimal("0.01"), mojos=False),),
            coins_to_exclude=(bytes32([0] * 32),),
        )
    )

    check_click_parsing(
        example_cs_cmd,
        "--min-coin-amount",
        "0.01",
        "--max-coin-amount",
        "0.01",
        "--exclude-amount",
        "0.01",
        "--exclude-coin",
        bytes32([0] * 32).hex(),
    )

    # again, convenience for testing sake
    assert example_cs_cmd.run() == CoinSelectionConfig(  # type: ignore[func-returns-value]
        min_coin_amount=uint64(1),
        max_coin_amount=uint64(1),
        excluded_coin_amounts=[uint64(1)],
        excluded_coin_ids=[bytes32([0] * 32)],
    )

    @chia_command(group=cmd, name="tx_config_cmd", short_help="blah", help="blah")
    class TXConfigCMD:
        tx_config_loader: NeedsTXConfig

        def run(self) -> None:
            # ignoring the `None` return here for convenient testing sake
            return self.tx_config_loader.load_tx_config(100, {}, 0)  # type: ignore[return-value]

    example_tx_config_cmd = TXConfigCMD(
        tx_config_loader=NeedsTXConfig(
            min_coin_amount=CliAmount(amount=Decimal("0.01"), mojos=False),
            max_coin_amount=CliAmount(amount=Decimal("0.01"), mojos=False),
            amounts_to_exclude=(CliAmount(amount=Decimal("0.01"), mojos=False),),
            coins_to_exclude=(bytes32([0] * 32),),
            reuse=False,
        )
    )

    check_click_parsing(
        example_tx_config_cmd,
        "--min-coin-amount",
        "0.01",
        "--max-coin-amount",
        "0.01",
        "--exclude-amount",
        "0.01",
        "--exclude-coin",
        bytes32([0] * 32).hex(),
        "--new-address",
    )

    # again, convenience for testing sake
    assert example_tx_config_cmd.run() == TXConfig(  # type: ignore[func-returns-value]
        min_coin_amount=uint64(1),
        max_coin_amount=uint64(1),
        excluded_coin_amounts=[uint64(1)],
        excluded_coin_ids=[bytes32([0] * 32)],
        reuse_puzhash=False,
    )


@pytest.mark.anyio
async def test_transaction_endpoint_mixin() -> None:
    @click.group()
    def cmd() -> None:
        pass  # pragma: no cover

    @chia_command(group=cmd, name="bad_cmd", short_help="blah", help="blah")
    class BadCMD(TransactionEndpoint):
        def run(self) -> None:  # type: ignore[override]
            pass  # pragma: no cover

    with pytest.raises(TypeError, match="transaction_endpoint_runner"):
        BadCMD(**STANDARD_TX_ENDPOINT_ARGS)

    @chia_command(group=cmd, name="cs_cmd", short_help="blah", help="blah")
    class TxCMD(TransactionEndpoint):
        @transaction_endpoint_runner
        async def run(self) -> list[TransactionRecord]:
            assert self.load_condition_valid_times() == ConditionValidTimes(
                min_time=uint64(10),
                max_time=uint64(20),
            )
            return []

    # Check that our default object lines up with the default options
    check_click_parsing(TxCMD(**STANDARD_TX_ENDPOINT_ARGS))

    example_tx_cmd = TxCMD(
        **{
            **STANDARD_TX_ENDPOINT_ARGS,
            **dict(
                fee=uint64(1_000_000_000_000 / 100),
                push=False,
                valid_at=10,
                expires_at=20,
            ),
        }
    )
    check_click_parsing(
        example_tx_cmd,
        "--fee",
        "0.01",
        "--no-push",
        "--valid-at",
        "10",
        "--expires-at",
        "20",
    )

    await example_tx_cmd.run()  # trigger inner assert


# While we sit in between two paradigms, this test is in place to ensure they remain in sync.
# Delete this if the old decorators are deleted.
def test_old_decorator_support() -> None:
    @click.group()
    def cmd() -> None:
        pass  # pragma: no cover

    @chia_command(group=cmd, name="cs_cmd", short_help="blah", help="blah")
    class CsCMD:
        coin_selection_loader: NeedsCoinSelectionConfig

        def run(self) -> None:
            pass  # pragma: no cover

    @chia_command(group=cmd, name="tx_config_cmd", short_help="blah", help="blah")
    class TXConfigCMD:
        tx_config_loader: NeedsTXConfig

        def run(self) -> None:
            pass  # pragma: no cover

    @chia_command(group=cmd, name="tx_cmd", short_help="blah", help="blah")
    class TxCMD(TransactionEndpoint):
        @transaction_endpoint_runner
        async def run(self) -> list[TransactionRecord]:
            return []  # pragma: no cover

    @chia_command(group=cmd, name="tx_w_tl_cmd", short_help="blah", help="blah")
    class TxWTlCMD(TransactionEndpointWithTimelocks):
        @transaction_endpoint_runner
        async def run(self) -> list[TransactionRecord]:
            return []  # pragma: no cover

    @cmd.command("cs_cmd_dec")
    @coin_selection_args
    def cs_cmd(**kwargs: Any) -> None:
        pass  # pragma: no cover

    @cmd.command("tx_config_cmd_dec")
    @tx_config_args
    def tx_config_cmd(**kwargs: Any) -> None:
        pass  # pragma: no cover

    @cmd.command("tx_cmd_dec")
    @tx_out_cmd(enable_timelock_args=False)  # type: ignore[arg-type]
    def tx_cmd(**kwargs: Any) -> None:
        pass  # pragma: no cover

    @cmd.command("tx_w_tl_cmd_dec")
    @tx_out_cmd(enable_timelock_args=True)  # type: ignore[arg-type]
    def tx_w_tl_cmd(**kwargs: Any) -> None:
        pass  # pragma: no cover

    for command_name, command in cmd.commands.items():
        if "_dec" in command_name:
            continue
        params = [param.to_info_dict() for param in cmd.commands[command_name].params]
        for param in cmd.commands[f"{command_name}_dec"].params:
            assert param.to_info_dict() in params
