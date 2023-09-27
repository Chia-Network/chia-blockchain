from __future__ import annotations

import pytest

from tests.wallet.conftest import WalletEnvironment, WalletTestFramework


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
async def test_basic_functionality(wallet_environments: WalletTestFramework) -> None:
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
