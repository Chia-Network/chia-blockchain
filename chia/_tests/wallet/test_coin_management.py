from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, List
from unittest.mock import patch

import pytest

from chia._tests.cmds.test_cmd_framework import check_click_parsing
from chia._tests.environments.wallet import STANDARD_TX_ENDPOINT_ARGS, WalletStateTransition, WalletTestFramework
from chia.cmds.cmd_classes import NeedsCoinSelectionConfig, NeedsWalletRPC, WalletClientInfo
from chia.cmds.coins import CombineCMD, ListCMD
from chia.cmds.param_types import CliAmount, cli_amount_none
from chia.rpc.rpc_client import ResponseFailureError
from chia.rpc.wallet_request_types import CombineCoins
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet

ONE_TRILLION = 1_000_000_000_000


@dataclass
class ValueAndArgs:
    value: Any
    args: List[Any]


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
        paginate=False,
    )

    await base_command.run()

    output = capsys.readouterr().out
    assert (
        textwrap.dedent(
            f"""\
        There are a total of {len(wallet_coins)} coins in wallet {env.wallet_aliases['xch']}.
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
        There are a total of {len(wallet_coins)} coins in wallet {env.wallet_aliases['xch']}.
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
        There are a total of {len(wallet_coins)} coins in wallet {env.wallet_aliases['xch']}.
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
        There are a total of {len(wallet_coins)} coins in wallet {env.wallet_aliases['xch']}.
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
        There are a total of 1 coins in wallet {env.wallet_aliases['cat']}.
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
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [2],
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="irrelevant")
@pytest.mark.anyio
async def test_combine_coins(wallet_environments: WalletTestFramework, capsys: pytest.CaptureFixture[str]) -> None:
    env = wallet_environments.environments[0]
    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    # Should have 4 coins, two 1.75 XCH, two 0.25 XCH

    # Grab one of the 0.25 ones to specify
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config) as action_scope:
        target_coin = list(await env.xch_wallet.select_coins(uint64(250_000_000_000), action_scope))[0]
        assert target_coin.amount == 250_000_000_000

    # These parameters will give us the maximum amount of behavior coverage
    # - More amount than the coin we specify
    # - Less amount than will have to be selected in order create it
    # - Higher # coins than necessary to create it
    fee = uint64(100)
    xch_combine_request = CombineCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            **dict(
                id=env.wallet_aliases["xch"],
                target_amount=CliAmount(amount=uint64(ONE_TRILLION), mojos=True),
                number_of_coins=uint16(3),
                input_coins=(target_coin.name(),),
                fee=fee,
                push=True,
            ),
        }
    )

    # Test some error cases first
    with pytest.raises(ResponseFailureError, match="greater then the maximum limit"):
        await replace(xch_combine_request, number_of_coins=uint16(501)).run()

    with pytest.raises(ResponseFailureError, match="You need at least two coins to combine"):
        await replace(xch_combine_request, number_of_coins=uint16(0)).run()

    with pytest.raises(ResponseFailureError, match="More coin IDs specified than desired number of coins to combine"):
        await replace(xch_combine_request, input_coins=(bytes32([0] * 32),) * 100).run()

    # We catch this one
    capsys.readouterr()
    await replace(xch_combine_request, id=50).run()
    output = (capsys.readouterr()).out
    assert "Wallet id: 50 not found" in output

    # This one only "works"" on the RPC
    env.wallet_state_manager.wallets[uint32(42)] = object()  # type: ignore[assignment]
    with pytest.raises(ResponseFailureError, match="Cannot combine coins from non-fungible wallet types"):
        assert xch_combine_request.target_amount is not None  # hey there mypy
        rpc_request = CombineCoins(
            wallet_id=uint32(42),
            target_coin_amount=xch_combine_request.target_amount.convert_amount(1),
            number_of_coins=uint16(xch_combine_request.number_of_coins),
            target_coin_ids=list(xch_combine_request.input_coins),
            fee=xch_combine_request.fee,
            push=xch_combine_request.push,
        )
        await env.rpc_client.combine_coins(rpc_request, wallet_environments.tx_config)

    del env.wallet_state_manager.wallets[uint32(42)]

    # Now push the request
    with patch("sys.stdin", new=io.StringIO("y\n")):
        await xch_combine_request.run()

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "spendable_balance": -2_250_000_000_000,
                        "pending_change": 2_250_000_000_000 - fee,
                        "max_send_amount": -2_250_000_000_000,
                        "pending_coin_removal_count": 3,
                    }
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        "spendable_balance": 2_250_000_000_000 - fee,
                        "pending_change": -(2_250_000_000_000 - fee),
                        "max_send_amount": 2_250_000_000_000 - fee,
                        "pending_coin_removal_count": -3,
                        "unspent_coin_count": -1,  # combine 3 into 1 + change
                    }
                },
            )
        ]
    )

    # Now do CATs
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        cat_wallet = await CATWallet.create_new_cat_wallet(
            env.wallet_state_manager,
            env.xch_wallet,
            {"identifier": "genesis_by_id"},
            uint64(50),
            action_scope,
        )

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

    BIG_COIN_AMOUNT = uint64(30)
    SMALL_COIN_AMOUNT = uint64(15)
    REALLY_SMALL_COIN_AMOUNT = uint64(5)
    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await cat_wallet.generate_signed_transaction(
            [BIG_COIN_AMOUNT, SMALL_COIN_AMOUNT, REALLY_SMALL_COIN_AMOUNT],
            [await env.xch_wallet.get_puzzle_hash(new=action_scope.config.tx_config.reuse_puzhash)] * 3,
            action_scope,
        )

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

    # We're going to test that we select the two smaller coins
    cat_combine_request = CombineCMD(
        **{
            **wallet_environments.cmd_tx_endpoint_args(env),
            **dict(
                id=env.wallet_aliases["cat"],
                target_amount=None,
                number_of_coins=uint16(2),
                input_coins=(),
                largest_first=False,
                fee=fee,
                push=True,
            ),
        }
    )

    with patch("sys.stdin", new=io.StringIO("y\n")):
        await cat_combine_request.run()
    # await cat_combine_request.run()

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -fee,
                        "set_remainder": True,  # We only really care that a fee was in fact attached
                    },
                    "cat": {
                        "spendable_balance": -SMALL_COIN_AMOUNT - REALLY_SMALL_COIN_AMOUNT,
                        "pending_change": SMALL_COIN_AMOUNT + REALLY_SMALL_COIN_AMOUNT,
                        "max_send_amount": -SMALL_COIN_AMOUNT - REALLY_SMALL_COIN_AMOUNT,
                        "pending_coin_removal_count": 2,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -fee,
                        "set_remainder": True,  # We only really care that a fee was in fact attached
                    },
                    "cat": {
                        "spendable_balance": SMALL_COIN_AMOUNT + REALLY_SMALL_COIN_AMOUNT,
                        "pending_change": -SMALL_COIN_AMOUNT - REALLY_SMALL_COIN_AMOUNT,
                        "max_send_amount": SMALL_COIN_AMOUNT + REALLY_SMALL_COIN_AMOUNT,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": -1,
                    },
                },
            )
        ]
    )
