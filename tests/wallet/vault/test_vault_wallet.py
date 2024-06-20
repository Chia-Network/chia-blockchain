from __future__ import annotations

import json
from hashlib import sha256
from typing import Awaitable, Callable, List

import pytest
from ecdsa import NIST256p, SigningKey
from ecdsa.util import PRNG

from chia.rpc.wallet_request_types import GatherSigningInfo
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.payment import Payment
from chia.wallet.signer_protocol import Spend
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import DEFAULT_COIN_SELECTION_CONFIG, DEFAULT_TX_CONFIG
from chia.wallet.vault.vault_info import RecoveryInfo, VaultInfo
from chia.wallet.vault.vault_root import VaultRoot
from chia.wallet.vault.vault_wallet import Vault
from tests.conftest import ConsensusMode
from tests.environments.wallet import WalletStateTransition, WalletTestFramework


async def vault_setup(wallet_environments: WalletTestFramework, with_recovery: bool) -> None:
    env = wallet_environments.environments[0]
    seed = b"chia_secp"
    SECP_SK = SigningKey.generate(curve=NIST256p, entropy=PRNG(seed), hashfunc=sha256)
    SECP_PK = SECP_SK.verifying_key.to_string("compressed")

    # Temporary hack so execute_signing_instructions can access the key
    env.wallet_state_manager.config["test_sk"] = SECP_SK
    client = wallet_environments.environments[1].rpc_client
    fingerprint = (await client.get_public_keys())[0]
    bls_pk = None
    timelock = None
    if with_recovery:
        bls_pk_hex = (await client.get_private_key(fingerprint))["pk"]
        bls_pk = bytes.fromhex(bls_pk_hex)
        timelock = uint64(10)
    hidden_puzzle_index = uint32(0)
    res = await client.vault_create(
        SECP_PK, hidden_puzzle_index, bls_pk=bls_pk, timelock=timelock, tx_config=DEFAULT_TX_CONFIG
    )
    vault_tx = res[0]
    assert vault_tx

    eve_coin = [item for item in vault_tx.additions if item not in vault_tx.removals and item.amount == 1][0]
    launcher_id = eve_coin.parent_coin_info
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
                        # "confirmed_wallet_balance": -1,
                        "set_remainder": True,
                    }
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "init": True,
                        "set_remainder": True,
                    }
                },
                post_block_balance_updates={
                    1: {
                        # "confirmed_wallet_balance": -1,
                        "set_remainder": True,
                    }
                },
            ),
        ]
    )
    await env.node.keychain_proxy.add_key(launcher_id.hex(), label="vault", private=False)
    await env.restart(vault_root.get_fingerprint())
    await wallet_environments.full_node.wait_for_wallet_synced(env.node, 20)


def sign_message(message: bytes) -> bytes:
    seed = b"chia_secp"
    SECP_SK = SigningKey.generate(curve=NIST256p, entropy=PRNG(seed), hashfunc=sha256)
    signed_message: bytes = SECP_SK.sign_deterministic(message)
    return signed_message


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1]}],
    indirect=True,
)
@pytest.mark.parametrize("setup_function", [vault_setup])
@pytest.mark.parametrize("with_recovery", [True, False])
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="requires secp")
@pytest.mark.anyio
async def test_vault_creation(
    wallet_environments: WalletTestFramework,
    setup_function: Callable[[WalletTestFramework, bool], Awaitable[None]],
    with_recovery: bool,
) -> None:
    await setup_function(wallet_environments, with_recovery)
    env = wallet_environments.environments[0]
    assert isinstance(env.xch_wallet, Vault)

    wallet: Vault = env.xch_wallet
    await wallet.sync_vault_launcher()
    assert wallet.vault_info

    # get a p2_singleton
    p2_singleton_puzzle_hash = wallet.get_p2_singleton_puzzle_hash()
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(1, p2_singleton_puzzle_hash)

    coins_to_create = 2
    funding_amount = uint64(1000000000)
    funding_wallet = wallet_environments.environments[1].xch_wallet
    for _ in range(coins_to_create):
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
                        "confirmed_wallet_balance": funding_amount * 2,
                        "set_remainder": True,
                    }
                },
            ),
        ],
    )

    recs = await wallet.select_coins(uint64(100), DEFAULT_COIN_SELECTION_CONFIG)
    coin = recs.pop()
    assert coin.amount == funding_amount
    recipient_ph = await funding_wallet.get_new_puzzlehash()

    primaries = [
        Payment(recipient_ph, uint64(500000000)),
        Payment(recipient_ph, uint64(510000000)),
    ]
    amount = uint64(1000000)
    fee = uint64(100)
    balance_delta = 1011000099

    unsigned_txs: List[TransactionRecord] = await wallet.generate_signed_transaction(
        amount, recipient_ph, DEFAULT_TX_CONFIG, primaries=primaries, fee=fee
    )
    assert len(unsigned_txs) == 1

    # Farm a block so the vault balance includes farmed coins from the test setup in pre-block update.
    # Do this after generating the tx so we can be sure to spend the right funding coins
    await wallet_environments.full_node.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

    assert unsigned_txs[0].spend_bundle is not None
    spends = [Spend.from_coin_spend(spend) for spend in unsigned_txs[0].spend_bundle.coin_spends]
    signing_info = await env.rpc_client.gather_signing_info(GatherSigningInfo(spends))

    signing_responses = await wallet.execute_signing_instructions(signing_info.signing_instructions)

    signed_response = await wallet.apply_signatures(spends, signing_responses)
    await env.wallet_state_manager.submit_transactions([signed_response])
    vault_eve_id = wallet.vault_info.coin.name()

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    1: {
                        "set_remainder": True,
                    }
                },
                post_block_balance_updates={
                    1: {
                        "confirmed_wallet_balance": -balance_delta,
                        "set_remainder": True,
                    }
                },
            ),
        ],
    )

    # check the wallet and singleton store have the latest vault coin
    assert wallet.vault_info.coin.parent_coin_info == vault_eve_id
    record = (await wallet.wallet_state_manager.singleton_store.get_records_by_coin_id(wallet.vault_info.coin.name()))[
        0
    ]
    assert record is not None

    assert isinstance(record.custom_data, bytes)
    custom_data = json.loads(record.custom_data)
    vault_info = VaultInfo.from_json_dict(custom_data["vault_info"])
    assert vault_info == wallet.vault_info
    recovery_info = RecoveryInfo.from_json_dict(custom_data["vault_info"]["recovery_info"])
    assert recovery_info == wallet.vault_info.recovery_info

    # test make_solution
    coin = (await wallet.select_coins(uint64(100), DEFAULT_COIN_SELECTION_CONFIG)).pop()
    wallet.make_solution(primaries, coin_id=coin.name())
    with pytest.raises(ValueError):
        wallet.make_solution(primaries)

    # test match_hinted_coin
    matched = await wallet.match_hinted_coin(wallet.vault_info.coin, wallet.vault_info.inner_puzzle_hash)
    assert matched


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1]}],
    indirect=True,
)
@pytest.mark.parametrize("setup_function", [vault_setup])
@pytest.mark.parametrize("with_recovery", [True])
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="requires secp")
@pytest.mark.anyio
async def test_vault_recovery(
    wallet_environments: WalletTestFramework,
    setup_function: Callable[[WalletTestFramework, bool], Awaitable[None]],
    with_recovery: bool,
) -> None:
    await setup_function(wallet_environments, with_recovery)
    env = wallet_environments.environments[0]
    assert isinstance(env.xch_wallet, Vault)
    recovery_seed = b"recovery_chia_secp"
    RECOVERY_SECP_SK = SigningKey.generate(curve=NIST256p, entropy=PRNG(recovery_seed), hashfunc=sha256)
    RECOVERY_SECP_PK = RECOVERY_SECP_SK.verifying_key.to_string("compressed")
    client = wallet_environments.environments[1].rpc_client
    fingerprint = (await client.get_public_keys())[0]
    bls_pk_hex = (await client.get_private_key(fingerprint))["pk"]
    bls_pk = bytes.fromhex(bls_pk_hex)
    timelock = uint64(10)

    wallet: Vault = env.xch_wallet
    await wallet.sync_vault_launcher()
    assert wallet.vault_info

    p2_singleton_puzzle_hash = wallet.get_p2_singleton_puzzle_hash()
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(1, p2_singleton_puzzle_hash)

    coins_to_create = 2
    funding_amount = uint64(1000000000)
    funding_wallet = wallet_environments.environments[1].xch_wallet
    for _ in range(coins_to_create):
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
                        "confirmed_wallet_balance": funding_amount * 2,
                        "set_remainder": True,
                    }
                },
            ),
        ],
    )

    [initiate_tx, finish_tx] = await env.rpc_client.vault_recovery(
        wallet_id=wallet.id(),
        secp_pk=RECOVERY_SECP_PK,
        hp_index=uint32(0),
        tx_config=DEFAULT_TX_CONFIG,
        bls_pk=bls_pk,
        timelock=timelock,
    )
    await wallet_environments.environments[1].rpc_client.push_transactions([initiate_tx], sign=True)

    vault_coin = wallet.vault_info.coin

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
                        "set_remainder": True,
                    }
                },
            ),
        ],
    )

    recovery_coin = wallet.vault_info.coin
    assert recovery_coin.parent_coin_info == vault_coin.name()

    wallet_environments.full_node.time_per_block = 100
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(count=2, guarantee_transaction_blocks=True)

    await wallet_environments.environments[1].rpc_client.push_transactions([finish_tx])

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
                        "set_remainder": True,
                    }
                },
            ),
        ],
    )

    recovered_coin = wallet.vault_info.coin
    assert recovered_coin.parent_coin_info == recovery_coin.name()
