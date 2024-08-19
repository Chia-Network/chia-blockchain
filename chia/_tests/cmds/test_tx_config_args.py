from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import click
from click.testing import CliRunner

from chia.cmds.cmds_util import CMDCoinSelectionConfigLoader, CMDTXConfigLoader, coin_selection_args, tx_config_args
from chia.cmds.param_types import CliAmount
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import create_default_chia_config, load_config


def test_coin_selection_args() -> None:
    @click.command()
    @coin_selection_args
    def test_cmd(
        min_coin_amount: CliAmount,
        max_coin_amount: CliAmount,
        coins_to_exclude: Sequence[bytes32],
        amounts_to_exclude: Sequence[CliAmount],
    ) -> None:
        print(
            CMDCoinSelectionConfigLoader(
                min_coin_amount,
                max_coin_amount,
                list(amounts_to_exclude),
                list(coins_to_exclude),
            )
            .to_coin_selection_config(1)
            .to_json_dict()
        )

    runner = CliRunner()

    result = runner.invoke(
        test_cmd,
        [
            "--min-coin-amount",
            "0.0",
            "--max-coin-amount",
            "0.0",
            "--exclude-coin",
            "0x0000000000000000000000000000000000000000000000000000000000000000",
            "--exclude-amount",
            "0.0",
        ],
        catch_exceptions=False,
    )

    assert (
        r"{'min_coin_amount': 0, 'max_coin_amount': 0, 'excluded_coin_amounts': [0], 'excluded_coin_ids': "
        r"['0x0000000000000000000000000000000000000000000000000000000000000000']}" in result.output
    )

    result = runner.invoke(
        test_cmd,
        [
            "--exclude-coin",
            "0x0000000000000000000000000000000000000000000000000000000000000000",
            "--exclude-coin",
            "0x1111111111111111111111111111111111111111111111111111111111111111",
            "--exclude-amount",
            "0.0",
            "--exclude-amount",
            "1.0",
        ],
        catch_exceptions=False,
    )

    assert (
        r"{'min_coin_amount': 0, 'max_coin_amount': 18446744073709551615, 'excluded_coin_amounts': [0, 1], "
        r"'excluded_coin_ids': ['0x0000000000000000000000000000000000000000000000000000000000000000', "
        r"'0x1111111111111111111111111111111111111111111111111111111111111111']}" in result.output
    )

    result = runner.invoke(
        test_cmd,
        [],
        catch_exceptions=False,
    )

    assert (
        r"{'min_coin_amount': 0, 'max_coin_amount': 18446744073709551615, 'excluded_coin_amounts': [], "
        r"'excluded_coin_ids': []}" in result.output
    )


def test_tx_config_args() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        create_default_chia_config(Path("."))
        config = load_config(Path("."), "config.yaml")
        config["reuse_public_key_for_change"] = {"1234567890": True}

        @click.command()
        @tx_config_args
        def test_cmd(
            min_coin_amount: CliAmount,
            max_coin_amount: CliAmount,
            coins_to_exclude: Sequence[bytes32],
            amounts_to_exclude: Sequence[CliAmount],
            reuse: Optional[bool],
        ) -> None:
            print(
                CMDTXConfigLoader(
                    min_coin_amount,
                    max_coin_amount,
                    list(amounts_to_exclude),
                    list(coins_to_exclude),
                    reuse,
                )
                .to_tx_config(1, config, 1234567890)
                .to_json_dict()
            )

        result = runner.invoke(
            test_cmd,
            [
                "--reuse-puzhash",
            ],
            catch_exceptions=False,
        )

        assert (
            r"{'min_coin_amount': 0, 'max_coin_amount': 18446744073709551615, 'excluded_coin_amounts': [], "
            r"'excluded_coin_ids': [], 'reuse_puzhash': True}" in result.output
        )

        result = runner.invoke(
            test_cmd,
            [
                "--new-address",
            ],
            catch_exceptions=False,
        )

        assert (
            r"{'min_coin_amount': 0, 'max_coin_amount': 18446744073709551615, 'excluded_coin_amounts': [], "
            r"'excluded_coin_ids': [], 'reuse_puzhash': False}" in result.output
        )

        result = runner.invoke(
            test_cmd,
            [],
            catch_exceptions=False,
        )

        assert (
            r"{'min_coin_amount': 0, 'max_coin_amount': 18446744073709551615, 'excluded_coin_amounts': [], "
            r"'excluded_coin_ids': [], 'reuse_puzhash': True}" in result.output
        )
