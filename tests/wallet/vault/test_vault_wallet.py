from __future__ import annotations

import types
from hashlib import sha256
from typing import Awaitable, Callable, Type

import pytest
from ecdsa import NIST256p, SigningKey

from chia.util.ints import uint32, uint64
from chia.util.observation_root import ObservationRoot
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.vault.vault_root import VaultRoot
from chia.wallet.vault.vault_wallet import Vault
from chia.wallet.wallet_protocol import MainWalletProtocol
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.conftest import ConsensusMode
from tests.wallet.conftest import WalletStateTransition, WalletTestFramework

SECP_SK = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
SECP_PK = SECP_SK.verifying_key.to_string("compressed")


async def vault_setup(
    wallet_environments: WalletTestFramework, monkeypatch: pytest.MonkeyPatch, with_recovery: bool
) -> None:
    def get_main_wallet_driver(self: WalletStateManager, observation_root: ObservationRoot) -> Type[MainWalletProtocol]:
        return Vault

    monkeypatch.setattr(
        WalletStateManager,
        "get_main_wallet_driver",
        types.MethodType(get_main_wallet_driver, WalletStateManager),
    )

    for env in wallet_environments.environments:
        SECP_SK = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
        SECP_PK = SECP_SK.verifying_key.to_string("compressed")
        client = env.rpc_client
        fingerprint = (await client.get_public_keys())[0]
        bls_pk = None
        timelock = None
        if with_recovery:
            bls_pk_hex = (await client.get_private_key(fingerprint))["pk"]
            bls_pk = bytes.fromhex(bls_pk_hex)
            timelock = uint64(1000)
        hidden_puzzle_index = uint32(0)
        res = await client.vault_create(
            SECP_PK, hidden_puzzle_index, bls_pk=bls_pk, timelock=timelock, tx_config=DEFAULT_TX_CONFIG
        )
        vault_tx = res[0]
        assert vault_tx

        eve_coin = [item for item in vault_tx.additions if item not in vault_tx.removals and item.amount == 1][0]
        launcher_id = eve_coin.name()
        vault_root = VaultRoot.from_bytes(launcher_id)
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        1: {
                            "init": True,
                            "set_remainder": True,
                        }
                    },
                    post_block_balance_updates={
                        1: {
                            "confirmed_wallet_balance": -1,
                            "set_remainder": True,
                        }
                    },
                )
            ]
        )
        await env.wallet_node.keychain_proxy.add_public_key(launcher_id.hex())
        await env.restart(vault_root.get_fingerprint())
        await wallet_environments.full_node.wait_for_wallet_synced(env.wallet_node, 20)


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize("setup_function", [vault_setup])
@pytest.mark.parametrize("with_recovery", [True, False])
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="requires secp")
@pytest.mark.anyio
async def test_vault_creation(
    setup_function: Callable[[WalletTestFramework, pytest.MonkeyPatch], Awaitable[None]],
    wallet_environments: WalletTestFramework,
    monkeypatch: pytest.MonkeyPatch,
    with_recovery: bool,
) -> None:
    await setup_function(wallet_environments, monkeypatch, with_recovery)
    env = wallet_environments.environments[0]
    assert isinstance(env.xch_wallet, Vault)

    wallet: Vault = env.xch_wallet
    await wallet.sync_singleton()
    assert wallet.vault_info

    if with_recovery:
        assert wallet.vault_info.is_recoverable
        assert wallet.recovery_info is not None
        recovery_spend, finish_spend = await wallet.create_recovery_spends()
        assert recovery_spend
        assert finish_spend
    else:
        assert not wallet.vault_info.is_recoverable
