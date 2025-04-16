from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia._tests.cmds.test_cmd_framework import check_click_parsing
from chia._tests.environments.wallet import STANDARD_TX_ENDPOINT_ARGS, WalletStateTransition, WalletTestFramework
from chia.cmds.cmd_helpers import NeedsCoinSelectionConfig, NeedsWalletRPC, WalletClientInfo
from chia.cmds.coins import CombineCMD, ListCMD, SplitCMD
from chia.cmds.param_types import CliAmount, cli_amount_none
from chia.rpc.wallet_request_types import GetSyncStatusResponse
from chia.wallet.cat_wallet.cat_wallet import CATWallet

ONE_TRILLION = 1_000_000_000_000


@dataclass
class ValueAndArgs:
    value: Any
    args: list[str]


@pytest.mark.parametrize(
    "id",
    [ValueAndArgs(1, []), ValueAndArgs(123, ["--id", "123"])],
)
@pytest.mark.parametrize(
    "show_unconfirmed",
    [ValueAndArgs(False, []), ValueAndArgs(True, ["--show-unconfirmed"])],
)
@pytest.mark.parametrize(
    "paginate",
    [ValueAndArgs(None, []), ValueAndArgs(True, ["--paginate"]), ValueAndArgs(False, ["--no-paginate"])],
)
def test_list_parsing(id: ValueAndArgs, show_unconfirmed: ValueAndArgs, paginate: ValueAndArgs) -> None:
    check_click_parsing(
        ListCMD(
            rpc_info=NeedsWalletRPC(client_info=None, wallet_rpc_port=None, fingerprint=None),
            coin_selection_config=NeedsCoinSelectionConfig(
                min_coin_amount=cli_amount_none,
                max_coin_amount=cli_amount_none,
                coins_to_exclude=(),
                amounts_to_exclude=(),
            ),
            id=id.value,
            show_unconfirmed=show_unconfirmed.value,
            paginate=paginate.value,
        ),
        *id.args,
        *show_unconfirmed.args,
        *paginate.args,
    )


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [3],  # 6 coins to test pagination
            "reuse_puzhash": True,  # irrelevent
            "trusted": True,  # irrelevent
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_list(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    client_info = WalletClientInfo(
        env.rpc_client,
        env.wallet_state_manager.root_pubkey.get_fingerprint(),
        env.wallet_state_manager.config,
    )

    wallet_coins = [cr.coin for cr in (await env.wallet_state_manager.coin_store.get_coin_records()).records]

    base_command = ListCMD(
        rpc_info=NeedsWalletRPC(client_info=client_info),
        coin_selection_config=NeedsCoinSelectionConfig(
            min_coin_amount=cli_amount_none,
            max_coin_amount=cli_amount_none,
            coins_to_exclude=(),
            amounts_to_exclude=(),
        ),
        id=env.wallet_aliases["xch"],
        show_unconfirmed=True,
        paginate=None,
    )

    # Test an error real quick
    await replace(base_command, id=50).run()
    output = (capsys.readouterr()).out
    assert "Wallet id: 50 not found" in output

    await base_command.run()

    output = capsys.readouterr().out
    assert (
        textwrap.dedent(
            f"""\
        There are a total of {len(wallet_coins)} coins in wallet {env.wallet_aliases["xch"]}.
        {len(wallet_coins)} confirmed coins.
        0 unconfirmed additions.
        0 unconfirmed removals.
        Confirmed coins:
        """
        )
        in output
    )
    for coin in wallet_coins:
        assert coin.name().hex() in output
        assert str(coin.amount) in output  # make sure we're always showing mojos as that's the only source of truth

    # Test pagination
    with patch("sys.stdin", new=io.StringIO("c\n")):
        await replace(base_command, paginate=True).run()

    output = capsys.readouterr().out
    assert (
        textwrap.dedent(
            f"""\
        There are a total of {len(wallet_coins)} coins in wallet {env.wallet_aliases["xch"]}.
        {len(wallet_coins)} confirmed coins.
        0 unconfirmed additions.
        0 unconfirmed removals.
        Confirmed coins:
        """
        )
        in output
    )
    for coin in wallet_coins:
        assert coin.name().hex() in output

    with patch("sys.stdin", new=io.StringIO("q\n")):
        await replace(base_command, paginate=True).run()

    output = capsys.readouterr().out
    assert (
        textwrap.dedent(
            f"""\
        There are a total of {len(wallet_coins)} coins in wallet {env.wallet_aliases["xch"]}.
        {len(wallet_coins)} confirmed coins.
        0 unconfirmed additions.
        0 unconfirmed removals.
        Confirmed coins:
        """
        )
        in output
    )
    count = 0
    for coin in wallet_coins:
        count += 1 if coin.name().hex() in output else 0
    assert count == 5

    # Create a cat wallet
    CAT_AMOUNT = uint64(50)
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await CATWallet.create_new_cat_wallet(
            env.wallet_state_manager,
            env.xch_wallet,
            {"identifier": "genesis_by_id"},
            CAT_AMOUNT,
            action_scope,
        )

    # Test showing unconfirmed
    # Currently:
    #   - 1 XCH coin is pending
    #   - 1 change will be created
    #   - 1 CAT ephemeral coin happened (1 removal & 1 addition)
    #   - 1 CAT coin is waiting to be created
    coin_used_in_tx = next(
        c for tx in action_scope.side_effects.transactions for c in tx.removals if c.amount != CAT_AMOUNT
    )
    change_coin = next(
        c for tx in action_scope.side_effects.transactions for c in tx.additions if c.amount != CAT_AMOUNT
    )

    await replace(base_command, show_unconfirmed=True).run()

    output = capsys.readouterr().out
    assert (
        textwrap.dedent(
            f"""\
        There are a total of {len(wallet_coins)} coins in wallet {env.wallet_aliases["xch"]}.
        {len(wallet_coins) - 1} confirmed coins.
        1 unconfirmed additions.
        1 unconfirmed removals.
        Confirmed coins:
        """
        )
        in output
    )
    assert coin_used_in_tx.name().hex() in output
    assert change_coin.name().hex() in output

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                # no need to test this, it is tested elsewhere
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"set_remainder": True},
                },
            )
        ]
    )

    # Test CAT display
    all_removals = {c for tx in action_scope.side_effects.transactions for c in tx.removals}
    cat_coin = next(
        c
        for tx in action_scope.side_effects.transactions
        for c in tx.additions
        if c.amount == CAT_AMOUNT and c not in all_removals
    )

    await replace(base_command, id=env.wallet_aliases["cat"]).run()

    output = capsys.readouterr().out
    assert (
        textwrap.dedent(
            f"""\
        There are a total of 1 coins in wallet {env.wallet_aliases["cat"]}.
        1 confirmed coins.
        0 unconfirmed additions.
        0 unconfirmed removals.
        Confirmed coins:
        """
        )
        in output
    )
    assert cat_coin.name().hex() in output
    assert str(CAT_AMOUNT) in output

    # Test a not synced error
    assert base_command.rpc_info.client_info is not None

    async def not_synced() -> GetSyncStatusResponse:
        return GetSyncStatusResponse(False, False)

    base_command.rpc_info.client_info.client.get_sync_status = not_synced  # type: ignore[method-assign]
    await base_command.run()
    output = (capsys.readouterr()).out
    assert "Wallet not synced. Please wait." in output


@pytest.mark.parametrize(
    "id",
    [ValueAndArgs(1, []), ValueAndArgs(123, ["--id", "123"])],
)
@pytest.mark.parametrize(
    "target_amount",
    [ValueAndArgs(None, []), ValueAndArgs(CliAmount(amount=Decimal("0.01"), mojos=False), ["--target-amount", "0.01"])],
)
@pytest.mark.parametrize(
    "number_of_coins",
    [ValueAndArgs(500, []), ValueAndArgs(1, ["--number-of-coins", "1"])],
)
@pytest.mark.parametrize(
    "input_coins",
    [
        ValueAndArgs((), []),
        ValueAndArgs((bytes32([0] * 32),), ["--input-coin", bytes32([0] * 32).hex()]),
        ValueAndArgs(
            (bytes32([0] * 32), bytes32([1] * 32)),
            ["--input-coin", bytes32([0] * 32).hex(), "--input-coin", bytes32([1] * 32).hex()],
        ),
    ],
)
@pytest.mark.parametrize(
    "largest_first",
    [ValueAndArgs(False, []), ValueAndArgs(True, ["--largest-first"])],
)
def test_combine_parsing(
    id: ValueAndArgs,
    target_amount: ValueAndArgs,
    number_of_coins: ValueAndArgs,
    input_coins: ValueAndArgs,
    largest_first: ValueAndArgs,
) -> None:
    check_click_parsing(
        CombineCMD(
            **STANDARD_TX_ENDPOINT_ARGS,
            id=id.value,
            target_amount=target_amount.value,
            number_of_coins=number_of_coins.value,
            input_coins=input_coins.value,
            largest_first=largest_first.value,
        ),
        *id.args,
        *target_amount.args,
        *number_of_coins.args,
        *input_coins.args,
        *largest_first.args,
    )


@pytest.mark.parametrize(
    "id",
    [ValueAndArgs(1, []), ValueAndArgs(123, ["--id", "123"])],
)
@pytest.mark.parametrize(
    "number_of_coins",
    [ValueAndArgs(1, ["--number-of-coins", "1"])],
)
@pytest.mark.parametrize(
    "amount_per_coin",
    [ValueAndArgs(CliAmount(amount=Decimal("0.01"), mojos=False), ["--amount-per-coin", "0.01"])],
)
@pytest.mark.parametrize(
    "target_coin_id",
    [
        ValueAndArgs(bytes32([0] * 32), ["--target-coin-id", bytes32([0] * 32).hex()]),
    ],
)
def test_split_parsing(
    id: ValueAndArgs,
    number_of_coins: ValueAndArgs,
    amount_per_coin: ValueAndArgs,
    target_coin_id: ValueAndArgs,
) -> None:
    check_click_parsing(
        SplitCMD(
            **STANDARD_TX_ENDPOINT_ARGS,
            id=id.value,
            number_of_coins=number_of_coins.value,
            amount_per_coin=amount_per_coin.value,
            target_coin_id=target_coin_id.value,
        ),
        *id.args,
        *number_of_coins.args,
        *amount_per_coin.args,
        *target_coin_id.args,
    )
