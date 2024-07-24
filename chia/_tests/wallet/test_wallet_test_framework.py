from __future__ import annotations

import pytest

from chia._tests.environments.wallet import (
    BalanceCheckingError,
    WalletEnvironment,
    WalletStateTransition,
    WalletTestFramework,
)
from chia.wallet.cat_wallet.cat_wallet import CATWallet


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "config_overrides": {
                "foo": "bar",  # A config value that never exists
                "min_mainnet_k_size": 2,  # A config value overriden
            },
            "blocks_needed": [1, 0],
        }
    ],
    indirect=True,
)
@pytest.mark.anyio
async def test_basic_functionality(wallet_environments: WalletTestFramework) -> None:
    env_0: WalletEnvironment = wallet_environments.environments[0]
    env_1: WalletEnvironment = wallet_environments.environments[1]

    assert await env_0.rpc_client.get_logged_in_fingerprint() is not None
    # assert await env_1.rpc_client.get_logged_in_fingerprint() is not None

    assert await env_0.xch_wallet.get_confirmed_balance() == 2_000_000_000_000
    assert await env_1.xch_wallet.get_confirmed_balance() == 0

    assert env_0.node.config["foo"] == "bar"
    assert env_0.wallet_state_manager.config["foo"] == "bar"
    assert wallet_environments.full_node.full_node.config["foo"] == "bar"

    assert env_0.node.config["min_mainnet_k_size"] == 2
    assert env_0.wallet_state_manager.config["min_mainnet_k_size"] == 2
    assert wallet_environments.full_node.full_node.config["min_mainnet_k_size"] == 2


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "config_overrides": {},
            "blocks_needed": [1],
            "trusted": True,
            "reuse_puzhash": True,
        },
    ],
    indirect=True,
)
@pytest.mark.anyio
async def test_balance_checking(
    wallet_environments: WalletTestFramework,
) -> None:
    env_0: WalletEnvironment = wallet_environments.environments[0]
    await env_0.check_balances()
    await wallet_environments.full_node.farm_blocks_to_wallet(count=1, wallet=env_0.xch_wallet)
    await wallet_environments.full_node.wait_for_wallet_synced(wallet_node=env_0.node, timeout=20)
    with pytest.raises(BalanceCheckingError, match="2000000000000 compared to balance response 4000000000000"):
        await env_0.check_balances()
    with pytest.raises(KeyError):
        await env_0.change_balances(
            {
                "xch": {
                    "confirmed_wallet_balance": 2_000_000_000_000,
                    "unconfirmed_wallet_balance": 2_000_000_000_000,
                    "spendable_balance": 2_000_000_000_000,
                    "max_send_amount": 2_000_000_000_000,
                    "unspent_coin_count": 2,
                }
            }
        )
    env_0.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }
    with pytest.raises(ValueError, match="Error before block was farmed"):
        await wallet_environments.process_pending_states([WalletStateTransition()])

    with pytest.raises(ValueError, match="Error after block was farmed"):
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": 2_000_000_000_000,
                            "unconfirmed_wallet_balance": 2_000_000_000_000,
                            "spendable_balance": 2_000_000_000_000,
                            "max_send_amount": 2_000_000_000_000,
                            "unspent_coin_count": 2,
                        }
                    },
                    post_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": 13,
                        }
                    },
                )
            ]
        )

    # this is necessary to undo the changes made before raising above
    await env_0.change_balances(
        {
            "xch": {
                "confirmed_wallet_balance": -2_000_000_000_013,
                "unconfirmed_wallet_balance": -2_000_000_000_000,
                "spendable_balance": -2_000_000_000_000,
                "max_send_amount": -2_000_000_000_000,
                "unspent_coin_count": -2,
            }
        }
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 2_000_000_000_000,
                        "unconfirmed_wallet_balance": 2_000_000_000_000,
                        "spendable_balance": 2_000_000_000_000,
                        "max_send_amount": 2_000_000_000_000,
                        "unspent_coin_count": 2,
                    }
                },
                post_block_balance_updates={
                    "xch": {
                        "set_remainder": True,
                    }
                },
            )
        ]
    )
    await CATWallet.get_or_create_wallet_for_cat(env_0.wallet_state_manager, env_0.xch_wallet, "00" * 32)
    with pytest.raises(KeyError, match="No wallet state for wallet id 2"):
        await env_0.check_balances()

    with pytest.raises(ValueError, match="if you intended to initialize its state"):
        await env_0.change_balances(
            {
                "cat": {
                    "confirmed_wallet_balance": 1_000_000,
                    "unconfirmed_wallet_balance": 0,
                    "spendable_balance": 0,
                    "pending_change": 0,
                    "max_send_amount": 0,
                    "unspent_coin_count": 0,
                    "pending_coin_removal_count": 0,
                }
            }
        )

    await env_0.change_balances(
        {
            "cat": {
                "init": True,
                "confirmed_wallet_balance": 1_000_000,
                "unconfirmed_wallet_balance": 0,
                "spendable_balance": 0,
                "pending_change": 0,
                "max_send_amount": 0,
                "unspent_coin_count": 0,
                "pending_coin_removal_count": 0,
            }
        }
    )

    with pytest.raises(BalanceCheckingError):
        await env_0.check_balances()

    # Test override
    await env_0.check_balances(additional_balance_info={"cat": {"confirmed_wallet_balance": 0}})
    with pytest.raises(BalanceCheckingError, match="not in balance response"):
        await env_0.check_balances(additional_balance_info={"xch": {"something not there": 0}})

    await env_0.change_balances({"cat": {"init": True, "set_remainder": True}})
    await env_0.check_balances()

    # Test special operators
    await wallet_environments.full_node.farm_blocks_to_wallet(count=1, wallet=env_0.xch_wallet)
    await wallet_environments.full_node.wait_for_wallet_synced(wallet_node=env_0.node, timeout=20)
    with pytest.raises(ValueError, match=r"\+ 2000000000000"):
        await env_0.change_balances(
            {
                "xch": {
                    "<#confirmed_wallet_balance": 2_000_000_000_000,
                }
            }
        )

    with pytest.raises(ValueError, match=r"\+ 2000000000000"):
        await env_0.change_balances(
            {
                "xch": {
                    ">#confirmed_wallet_balance": 2_000_000_000_000,
                }
            }
        )

    with pytest.raises(ValueError, match=r"\+ 1999999999999"):
        await env_0.change_balances(
            {
                "xch": {
                    "<=#confirmed_wallet_balance": 1_999_999_999_999,
                }
            }
        )

    with pytest.raises(ValueError, match=r"\+ 2000000000001"):
        await env_0.change_balances(
            {
                "xch": {
                    ">=#confirmed_wallet_balance": 2_000_000_000_001,
                }
            }
        )

    wallet_states_save = env_0.wallet_states.copy()

    await env_0.change_balances(
        {
            "xch": {
                "<#confirmed_wallet_balance": 2_000_000_000_001,
                "set_remainder": True,
            }
        }
    )
    await env_0.check_balances()
    env_0.wallet_states = wallet_states_save

    await env_0.change_balances(
        {
            "xch": {
                ">#confirmed_wallet_balance": 1_999_999_999_999,
                "set_remainder": True,
            }
        }
    )
    await env_0.check_balances()
    env_0.wallet_states = wallet_states_save

    await env_0.change_balances(
        {
            "xch": {
                ">=#confirmed_wallet_balance": 2_000_000_000_000,
                "set_remainder": True,
            }
        }
    )
    await env_0.check_balances()
    env_0.wallet_states = wallet_states_save

    await env_0.change_balances(
        {
            "xch": {
                "<=#confirmed_wallet_balance": 2_000_000_000_000,
                "set_remainder": True,
            }
        }
    )
    await env_0.check_balances()
