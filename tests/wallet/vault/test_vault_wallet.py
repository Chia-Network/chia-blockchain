from __future__ import annotations

from hashlib import sha256

import pytest
from clvm.casts import int_to_bytes
from ecdsa import NIST256p, SigningKey

from chia.util.ints import uint64
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from tests.conftest import ConsensusMode
from tests.wallet.conftest import WalletTestFramework

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
    # full_node_api: FullNodeSimulator = wallet_environments.full_node
    env = wallet_environments.environments[0]
    # wallet_node = env.wallet_node
    # wallet = env.xch_wallet
    client = env.rpc_client

    fingerprint = (await client.get_public_keys())[0]
    bls_pk_hex = (await client.get_private_key(fingerprint))["pk"]
    bls_pk = bytes.fromhex(bls_pk_hex)

    timelock = uint64(1000)
    entropy = int_to_bytes(101)

    res = await client.vault_create(SECP_PK, entropy, bls_pk, timelock, tx_config=DEFAULT_TX_CONFIG, fee=uint64(10))
    vault_tx = res[0]
    assert vault_tx

    eve_coin = [item for item in vault_tx.additions if item not in vault_tx.removals and item.amount == 1][0]
    assert eve_coin
