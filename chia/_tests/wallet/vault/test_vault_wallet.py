from __future__ import annotations

from hashlib import sha256

import pytest
from ecdsa import NIST256p, SigningKey

from chia._tests.conftest import ConsensusMode
from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.util.ints import uint32, uint64
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG

SECP_SK = SigningKey.generate(curve=NIST256p, hashfunc=sha256)
SECP_PK = SECP_SK.verifying_key.to_string("compressed")


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
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="requires secp")
@pytest.mark.anyio
async def test_vault_creation(wallet_environments: WalletTestFramework) -> None:
    # Setup
    env = wallet_environments.environments[0]
    client = env.rpc_client

    fingerprint = (await client.get_public_keys())[0]
    bls_pk_hex = (await client.get_private_key(fingerprint))["pk"]
    bls_pk = bytes.fromhex(bls_pk_hex)

    timelock = uint64(1000)
    hp_index = uint32(1)

    res = await client.vault_create(SECP_PK, hp_index, bls_pk, timelock, tx_config=DEFAULT_TX_CONFIG, fee=uint64(10))
    vault_tx = res[0]
    assert vault_tx

    eve_coin = [item for item in vault_tx.additions if item not in vault_tx.removals and item.amount == 1][0]
    assert eve_coin

    await env.wallet_state_manager.add_pending_transactions(res)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "unconfirmed_wallet_balance": -11,  # 1 for vault singleton, 10 for fee
                        "pending_coin_removal_count": 2,
                        "<=#spendable_balance": -11,
                        "<=#max_send_amount": -11,
                        "set_remainder": True,
                    }
                },
                post_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": -11,
                        "set_remainder": True,
                    }
                },
            )
        ]
    )
