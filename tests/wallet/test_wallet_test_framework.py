from __future__ import annotations

from typing import Dict, Generator, List

import pytest

from chia.wallet.cat_wallet.cat_wallet import CATWallet
from tests.wallet.conftest import WalletEnvironment, WalletTestFramework


@pytest.fixture(scope="session")
def track_trusted() -> Generator[Dict[str, List[bool]], None, None]:
    trusted_dict: Dict[str, List[bool]] = {}
    yield trusted_dict
    for key, value in trusted_dict.items():
        if len(value) != 2 or True not in value or False not in value:
            raise ValueError(f"Test {key} did not do exactly trusted and untrusted: {value}")


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
@pytest.mark.asyncio
async def test_basic_functionality(
    track_trusted: Dict[str, List[bool]], wallet_environments: WalletTestFramework
) -> None:
    track_trusted.setdefault("test_basic_functionality", [])
    track_trusted["test_basic_functionality"].append(wallet_environments.trusted_full_node)

    env_0: WalletEnvironment = wallet_environments.environments[0]
    env_1: WalletEnvironment = wallet_environments.environments[1]

    assert await env_0.rpc_client.get_logged_in_fingerprint() is not None
    # assert await env_1.rpc_client.get_logged_in_fingerprint() is not None

    assert await env_0.xch_wallet.get_confirmed_balance() == 2_000_000_000_000
    assert await env_1.xch_wallet.get_confirmed_balance() == 0

    assert env_0.wallet_node.config["foo"] == "bar"
    assert env_0.wallet_state_manager.config["foo"] == "bar"
    assert wallet_environments.full_node.full_node.config["foo"] == "bar"

    assert env_0.wallet_node.config["min_mainnet_k_size"] == 2
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
        },
    ],
    indirect=True,
)
@pytest.mark.asyncio
async def test_balance_checking(
    wallet_environments: WalletTestFramework,
) -> None:
    env_0: WalletEnvironment = wallet_environments.environments[0]
    await env_0.check_balances()
    await wallet_environments.full_node.farm_blocks_to_wallet(count=1, wallet=env_0.xch_wallet)
    await wallet_environments.full_node.wait_for_wallet_synced(wallet_node=env_0.wallet_node, timeout=20)
    with pytest.raises(ValueError, match="2000000000000 compared to balance response 4000000000000"):
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
    await env_0.check_balances()
    await wallet_environments.full_node.farm_blocks_to_wallet(count=1, wallet=env_0.xch_wallet)
    await wallet_environments.full_node.wait_for_wallet_synced(wallet_node=env_0.wallet_node, timeout=20)
    await env_0.change_balances(
        {
            "xch": {
                "set_remainder": True,
            }
        }
    )
    await env_0.check_balances()
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

    with pytest.raises(ValueError):
        await env_0.check_balances()

    # Test override
    await env_0.check_balances(additional_balance_info={"cat": {"confirmed_wallet_balance": 0}})

    await env_0.change_balances({"cat": {"init": True, "set_remainder": True}})
    await env_0.check_balances()
