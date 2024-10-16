from __future__ import annotations

from typing import Awaitable, Callable

import pytest
from chia_rs import G1Element
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from chia._tests.conftest import ConsensusMode
from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia.rpc.wallet_request_types import GetPrivateKey, PushTransactions, VaultCreate, VaultRecovery
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.util.keychain import KeyTypes
from chia.wallet.payment import Payment
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.vault.vault_info import VaultInfo
from chia.wallet.vault.vault_root import VaultRoot
from chia.wallet.vault.vault_wallet import Vault


async def vault_setup(wallet_environments: WalletTestFramework, with_recovery: bool) -> None:
    env = wallet_environments.environments[0]
    seed = 0x1A62C9636D1C9DB2E7D564D0C11603BF456AAD25AA7B12BDFD762B4E38E7EDC6
    SECP_SK = ec.derive_private_key(seed, ec.SECP256R1(), default_backend())
    SECP_PK = SECP_SK.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)

    # Temporary hack so execute_signing_instructions can access the key
    env.wallet_state_manager.config["test_sk"] = SECP_SK
    client = wallet_environments.environments[1].rpc_client
    fingerprint = (await client.get_public_keys()).pk_fingerprints[0]
    bls_pk = None
    timelock = None
    if with_recovery:
        bls_pk = (await client.get_private_key(GetPrivateKey(fingerprint))).private_key.observation_root()
        timelock = uint64(10)
    if bls_pk is not None:
        assert isinstance(bls_pk, G1Element)
    hidden_puzzle_index = uint32(0)
    res = await client.vault_create(
        VaultCreate(
            secp_pk=SECP_PK,
            hp_index=hidden_puzzle_index,
            bls_pk=bls_pk,
            timelock=timelock,
            push=True,
        ),
        tx_config=wallet_environments.tx_config,
    )

    all_removals = [coin for tx in res.transactions for coin in tx.removals]
    eve_coin = [
        item for tx in res.transactions for item in tx.additions if item not in all_removals and item.amount == 1
    ][0]
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
    await env.node.keychain_proxy.add_key(
        launcher_id.hex(), label="vault", private=False, key_type=KeyTypes.VAULT_LAUNCHER
    )
    await env.restart(vault_root.get_fingerprint())
    await wallet_environments.full_node.wait_for_wallet_synced(env.node, 20)


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

    coins_to_create = 2
    funding_amount = uint64(1000000000)
    funding_wallet = wallet_environments.environments[1].xch_wallet
    for _ in range(coins_to_create):
        async with funding_wallet.wallet_state_manager.new_action_scope(
            DEFAULT_TX_CONFIG, push=True, sign=True
        ) as action_scope:
            await funding_wallet.generate_signed_transaction(
                funding_amount,
                p2_singleton_puzzle_hash,
                action_scope,
                memos=[wallet.vault_info.pubkey],
            )

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

    recipient_ph = await funding_wallet.get_new_puzzlehash()

    primaries = [
        Payment(recipient_ph, uint64(500000000), memos=[recipient_ph]),
        Payment(recipient_ph, uint64(510000000), memos=[recipient_ph]),
    ]
    amount = uint64(1000000)
    fee = uint64(100)
    balance_delta = 1011000099

    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True, sign=True) as action_scope:
        await wallet.generate_signed_transaction(
            amount, recipient_ph, action_scope, primaries=primaries, fee=fee, memos=[recipient_ph]
        )

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
    custom_data = record.custom_data
    vault_info = VaultInfo.from_bytes(custom_data)
    assert vault_info == wallet.vault_info
    assert vault_info.recovery_info == wallet.vault_info.recovery_info


@pytest.mark.parametrize(
    "wallet_environments",
    [{"num_environments": 2, "blocks_needed": [1, 1]}],
    indirect=True,
)
@pytest.mark.parametrize("setup_function", [vault_setup])
@pytest.mark.parametrize("with_recovery", [True])
@pytest.mark.parametrize("spent_recovery", [True, False])
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="requires secp")
@pytest.mark.anyio
async def test_vault_recovery(
    wallet_environments: WalletTestFramework,
    setup_function: Callable[[WalletTestFramework, bool], Awaitable[None]],
    with_recovery: bool,
    spent_recovery: bool,
) -> None:
    await setup_function(wallet_environments, with_recovery)
    env = wallet_environments.environments[0]
    assert isinstance(env.xch_wallet, Vault)
    recovery_seed = 0x6D836489B057E59FF0E16CE2D8F876C454697B76549E11D93F8102C4140B2DC5
    RECOVERY_SECP_SK = ec.derive_private_key(recovery_seed, ec.SECP256R1(), default_backend())
    RECOVERY_SECP_PK = RECOVERY_SECP_SK.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    client = wallet_environments.environments[1].rpc_client
    fingerprint = (await client.get_public_keys()).pk_fingerprints[0]
    bls_pk = (await client.get_private_key(GetPrivateKey(fingerprint))).private_key.observation_root()
    assert isinstance(bls_pk, G1Element)
    timelock = uint64(10)

    wallet: Vault = env.xch_wallet
    await wallet.sync_vault_launcher()
    assert wallet.vault_info

    p2_addr = await wallet_environments.environments[0].rpc_client.get_next_address(wallet.id(), False)

    funding_amount = uint64(1000000000)
    funding_wallet = wallet_environments.environments[1].xch_wallet
    await wallet_environments.environments[1].rpc_client.send_transaction(
        funding_wallet.id(), funding_amount, p2_addr, DEFAULT_TX_CONFIG
    )

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
                        "confirmed_wallet_balance": funding_amount,
                        "set_remainder": True,
                    }
                },
            ),
        ],
    )

    # make a spend before recovery
    if spent_recovery:
        amount = uint64(10000)
        recipient_ph = await funding_wallet.get_new_puzzlehash()
        async with wallet.wallet_state_manager.new_action_scope(
            DEFAULT_TX_CONFIG, push=False, sign=False
        ) as action_scope:
            await wallet.generate_signed_transaction(amount, recipient_ph, action_scope, memos=[recipient_ph])

        await wallet_environments.environments[0].rpc_client.push_transactions(
            PushTransactions(  # pylint: disable=unexpected-keyword-arg
                transactions=action_scope.side_effects.transactions,
                sign=True,
            ),
            tx_config=wallet_environments.tx_config,
        )

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
                            "confirmed_wallet_balance": -amount + 1,
                            "set_remainder": True,
                        }
                    },
                ),
            ],
        )

    [initiate_tx, finish_tx] = (
        await env.rpc_client.vault_recovery(
            VaultRecovery(
                wallet_id=wallet.id(),
                secp_pk=RECOVERY_SECP_PK,
                hp_index=uint32(0),
                bls_pk=bls_pk,
                timelock=timelock,
                sign=False,
            ),
            tx_config=wallet_environments.tx_config,
        )
    ).transactions

    await wallet_environments.environments[1].rpc_client.push_transactions(
        PushTransactions(  # pylint: disable=unexpected-keyword-arg
            transactions=[initiate_tx],
            sign=True,
        ),
        tx_config=wallet_environments.tx_config,
    )

    vault_coin = wallet.vault_info.coin

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
                        "<=#confirmed_wallet_balance": 1,
                        "set_remainder": True,
                    }
                },
            ),
        ],
    )

    recovery_coin = wallet.vault_info.coin
    assert recovery_coin.parent_coin_info == vault_coin.name()

    wallet_environments.full_node.time_per_block = 100
    await wallet_environments.full_node.farm_blocks_to_puzzlehash(
        count=2, guarantee_transaction_blocks=True, farm_to=bytes32(b"1" * 32)
    )

    await wallet_environments.environments[1].rpc_client.push_transactions(
        PushTransactions(transactions=[finish_tx]), tx_config=wallet_environments.tx_config
    )

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
                        "<=#confirmed_wallet_balance": 1,
                        "set_remainder": True,
                    }
                },
            ),
        ],
    )

    recovered_coin = wallet.vault_info.coin
    assert recovered_coin.parent_coin_info == recovery_coin.name()

    # spend recovery balance
    env.wallet_state_manager.config["test_sk"] = RECOVERY_SECP_SK
    recipient_ph = await funding_wallet.get_new_puzzlehash()
    amount = uint64(200)

    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False, sign=False) as action_scope:
        await wallet.generate_signed_transaction(amount, recipient_ph, action_scope, memos=[recipient_ph])

    # Test we can push the transaction separately
    await wallet_environments.environments[0].rpc_client.push_transactions(
        PushTransactions(  # pylint: disable=unexpected-keyword-arg
            transactions=action_scope.side_effects.transactions,
            sign=True,
        ),
        tx_config=wallet_environments.tx_config,
    )
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
                        "confirmed_wallet_balance": -amount - 1,
                        "set_remainder": True,
                    }
                },
            ),
        ],
    )
