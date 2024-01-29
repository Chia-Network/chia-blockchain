from __future__ import annotations

from hashlib import sha256
from typing import Awaitable, Callable

import pytest
from ecdsa import NIST256p, SigningKey
from ecdsa.util import PRNG

from chia.util.ints import uint32, uint64
from chia.wallet.util.tx_config import DEFAULT_COIN_SELECTION_CONFIG, DEFAULT_TX_CONFIG
from chia.wallet.vault.vault_root import VaultRoot
from chia.wallet.vault.vault_wallet import Vault
from tests.conftest import ConsensusMode
from tests.environments.wallet import WalletStateTransition, WalletTestFramework


async def vault_setup(wallet_environments: WalletTestFramework, with_recovery: bool) -> None:
    env = wallet_environments.environments[0]
    seed = b"chia_secp"
    SECP_SK = SigningKey.generate(curve=NIST256p, entropy=PRNG(seed), hashfunc=sha256)
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
            "num_environments": 2,
            "blocks_needed": [1, 1],
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize("setup_function", [vault_setup])
@pytest.mark.parametrize("with_recovery", [True, False])
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="requires secp")
@pytest.mark.anyio
async def test_vault_creation(
    setup_function: Callable[[WalletTestFramework, bool], Awaitable[None]],
    wallet_environments: WalletTestFramework,
    with_recovery: bool,
) -> None:
    await setup_function(wallet_environments, with_recovery)
    env = wallet_environments.environments[0]
    assert isinstance(env.xch_wallet, Vault)

    wallet: Vault = env.xch_wallet
    await wallet.sync_singleton()
    assert wallet.vault_info

    # get a p2_singleton
    p2_singleton_puzzle_hash = wallet.get_p2_singleton_puzzle_hash()
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(1, p2_singleton_puzzle_hash)
    # launcher_id = wallet.vault_info.launcher_id

    if with_recovery:
        assert wallet.vault_info.is_recoverable
        assert wallet.recovery_info is not None
        [recovery_spend, finish_spend] = await wallet.create_recovery_spends()
        assert recovery_spend
        assert finish_spend
    else:
        assert not wallet.vault_info.is_recoverable

    funding_amount = uint64(1000000000)
    funding_wallet = wallet_environments.environments[1].xch_wallet
    funding_tx = await funding_wallet.generate_signed_transaction(
        funding_amount,
        p2_singleton_puzzle_hash,
        DEFAULT_TX_CONFIG,
        memos=[wallet.vault_info.pubkey],
    )
    await funding_wallet.wallet_state_manager.add_pending_transactions(funding_tx)

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
                        # "confirmed_wallet_balance": -funding_amount,
                        "set_remainder": True,
                    }
                },
            )
        ],
    )

    recs = await wallet.select_coins(uint64(100), DEFAULT_COIN_SELECTION_CONFIG)
    assert recs
