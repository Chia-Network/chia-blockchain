from __future__ import annotations

import dataclasses
from typing import Any, Awaitable, Callable, List, Optional

import pytest
from chia_rs import G2Element
from typing_extensions import Literal

from chia._tests.environments.wallet import WalletEnvironment, WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert_not_none
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.blockchain_format.coin import coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, construct_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.util.query_filter import TransactionTypeFilter
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.cr_cat_drivers import ProofsChecker, construct_cr_layer
from chia.wallet.vc_wallet.cr_cat_wallet import CRCATWallet
from chia.wallet.vc_wallet.vc_store import VCProofs, VCRecord
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


async def mint_cr_cat(
    num_blocks: int,
    wallet_0: Wallet,
    wallet_node_0: WalletNode,
    client_0: WalletRpcClient,
    full_node_api: FullNodeSimulator,
    authorized_providers: List[bytes32] = [],
    tail: Program = Program.to(None),
    proofs_checker: ProofsChecker = ProofsChecker(["foo", "bar"]),
) -> None:
    our_puzzle: Program = await wallet_0.get_new_puzzle()
    cat_puzzle: Program = construct_cat_puzzle(
        CAT_MOD,
        tail.get_tree_hash(),
        Program.to(1),
    )
    CAT_AMOUNT_0 = uint64(100)

    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)
    tx = (
        await client_0.create_signed_transactions(
            [
                {
                    "puzzle_hash": cat_puzzle.get_tree_hash(),
                    "amount": CAT_AMOUNT_0,
                }
            ],
            DEFAULT_TX_CONFIG,
            wallet_id=1,
        )
    ).signed_tx
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None

    # Do the eve spend back to our wallet and add the CR layer
    cat_coin = next(c for c in spend_bundle.additions() if c.amount == CAT_AMOUNT_0)
    eve_spend = WalletSpendBundle(
        [
            make_spend(
                cat_coin,
                cat_puzzle,
                Program.to(
                    [
                        Program.to(
                            [
                                [
                                    51,
                                    construct_cr_layer(
                                        authorized_providers,
                                        proofs_checker.as_program(),
                                        our_puzzle,
                                    ).get_tree_hash(),
                                    CAT_AMOUNT_0,
                                    [our_puzzle.get_tree_hash()],
                                ],
                                [51, None, -113, tail, None],
                                [1, our_puzzle.get_tree_hash(), authorized_providers, proofs_checker.as_program()],
                            ]
                        ),
                        None,
                        cat_coin.name(),
                        coin_as_list(cat_coin),
                        [cat_coin.parent_coin_info, Program.to(1).get_tree_hash(), cat_coin.amount],
                        0,
                        0,
                    ]
                ),
            )
        ],
        G2Element(),
    )
    spend_bundle = WalletSpendBundle.aggregate([spend_bundle, eve_spend])
    await wallet_node_0.wallet_state_manager.add_pending_transactions(
        [dataclasses.replace(tx, spend_bundle=spend_bundle, name=spend_bundle.name())]
    )
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "config_overrides": {"automatically_add_unknown_cats": True},
            "blocks_needed": [2, 1],
        }
    ],
    indirect=True,
)
@pytest.mark.anyio
async def test_vc_lifecycle(wallet_environments: WalletTestFramework) -> None:
    # Setup
    full_node_api: FullNodeSimulator = wallet_environments.full_node
    env_0 = wallet_environments.environments[0]
    env_1 = wallet_environments.environments[1]
    wallet_node_0 = wallet_environments.environments[0].node
    wallet_node_1 = wallet_environments.environments[1].node
    wallet_0 = wallet_environments.environments[0].xch_wallet
    wallet_1 = wallet_environments.environments[1].xch_wallet
    client_0 = wallet_environments.environments[0].rpc_client
    client_1 = wallet_environments.environments[1].rpc_client

    # Define wallet aliases
    env_0.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "vc": 3,
        "crcat": 4,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "crcat": 2,
        "vc": 3,
    }

    # Generate DID as an "authorized provider"
    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        did_id: bytes32 = bytes32.from_hexstr(
            (
                await DIDWallet.create_new_did_wallet(
                    wallet_node_0.wallet_state_manager, wallet_0, uint64(1), action_scope
                )
            ).get_my_DID()
        )

    # Mint a VC
    vc_record = (
        await client_0.vc_mint(
            did_id,
            wallet_environments.tx_config,
            target_address=await wallet_0.get_new_puzzlehash(),
            fee=uint64(1_750_000_000_000),
        )
    ).vc_record

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        # 1_750_000_000_000 for VC mint fee, 1 for VC singleton, 1 for DID mint
                        "unconfirmed_wallet_balance": -1_750_000_000_002,
                        # I'm not sure incrementing pending_coin_removal_count here by 3 is the spirit of this number
                        # One existing coin has been removed and two ephemeral coins have been removed
                        # Does pending_coin_removal_count attempt to show the number of current pending removals
                        # Or does it intend to just mean all pending removals that we should eventually get states for?
                        "pending_coin_removal_count": 5,  # 4 for VC mint, 1 for DID mint
                        "<=#spendable_balance": -1_750_000_000_002,
                        "<=#max_send_amount": -1_750_000_000_002,
                        "set_remainder": True,
                    },
                    "did": {"init": True, "set_remainder": True},
                    "vc": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "pending_change": 0,
                        "max_send_amount": 0,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        # 1_750_000_000_000 for VC mint fee, 1 for VC singleton, 1 for DID mint
                        "confirmed_wallet_balance": -1_750_000_000_002,
                        "pending_coin_removal_count": -5,  # 3 for VC mint, 1 for DID mint
                        "set_remainder": True,
                    },
                    "did": {
                        "set_remainder": True,
                    },
                    "vc": {
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )
    new_vc_record: Optional[VCRecord] = await client_0.vc_get(vc_record.vc.launcher_id)
    assert new_vc_record is not None

    # Spend VC
    proofs: VCProofs = VCProofs({"foo": "1", "bar": "1", "baz": "1", "qux": "1", "grault": "1"})
    proof_root: bytes32 = proofs.root()
    await client_0.vc_spend(
        vc_record.vc.launcher_id,
        wallet_environments.tx_config,
        new_proof_hash=proof_root,
        fee=uint64(100),
    )
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -100,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -100,
                        "<=#max_send_amount": -100,
                        "set_remainder": True,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -100,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )
    vc_record_updated: Optional[VCRecord] = await client_0.vc_get(vc_record.vc.launcher_id)
    assert vc_record_updated is not None
    assert vc_record_updated.vc.proof_hash == proof_root

    # Do a mundane spend
    await client_0.vc_spend(vc_record.vc.launcher_id, wallet_environments.tx_config)
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    # Add proofs to DB
    await client_0.vc_add_proofs(proofs.key_value_pairs)
    await client_0.vc_add_proofs(proofs.key_value_pairs)  # Doing it again just to make sure it doesn't care
    assert await client_0.vc_get_proofs_for_root(proof_root) == proofs.key_value_pairs
    vc_records, fetched_proofs = await client_0.vc_get_list()
    assert len(vc_records) == 1
    assert fetched_proofs[proof_root.hex()] == proofs.key_value_pairs

    # Mint CR-CAT
    await mint_cr_cat(1, wallet_0, wallet_node_0, client_0, full_node_api, [did_id])
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -100,
                        "<=#spendable_balance": -100,
                        "<=#max_send_amount": -100,
                        "set_remainder": True,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -100,
                        "set_remainder": True,
                    },
                    "crcat": {
                        "init": True,
                        "confirmed_wallet_balance": 100,
                        "unconfirmed_wallet_balance": 100,
                        "spendable_balance": 100,
                        "pending_change": 0,
                        "max_send_amount": 100,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": 0,
                    },
                },
            ),
            WalletStateTransition(),
        ]
    )

    cr_cat_wallet_0 = wallet_node_0.wallet_state_manager.wallets[env_0.dealias_wallet_id("crcat")]
    assert isinstance(cr_cat_wallet_0, CRCATWallet)
    assert await CRCATWallet.create(  # just testing the create method doesn't throw
        wallet_node_0.wallet_state_manager,
        wallet_node_0.wallet_state_manager.main_wallet,
        (await wallet_node_0.wallet_state_manager.get_all_wallet_info_entries(wallet_type=WalletType.CRCAT))[0],
    )
    assert {
        "data": bytes(cr_cat_wallet_0.info).hex(),
        "id": env_0.dealias_wallet_id("crcat"),
        "name": cr_cat_wallet_0.get_name(),
        "type": cr_cat_wallet_0.type(),
        "authorized_providers": [p.hex() for p in cr_cat_wallet_0.info.authorized_providers],
        "flags_needed": cr_cat_wallet_0.info.proofs_checker.flags,
    } == (await client_0.get_wallets(wallet_type=cr_cat_wallet_0.type()))[0]
    assert await wallet_node_0.wallet_state_manager.get_wallet_for_asset_id(cr_cat_wallet_0.get_asset_id()) is not None
    wallet_1_ph = await wallet_1.get_new_puzzlehash()
    wallet_1_addr = encode_puzzle_hash(wallet_1_ph, "txch")
    txs = (
        await client_0.cat_spend(
            cr_cat_wallet_0.id(),
            wallet_environments.tx_config,
            uint64(90),
            wallet_1_addr,
            uint64(2000000000),
            memos=["hey"],
        )
    ).transactions
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -2000000000,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -2000000000,
                        "<=#max_send_amount": -2000000000,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                    "crcat": {
                        "unconfirmed_wallet_balance": -90,
                        "spendable_balance": -100,
                        "max_send_amount": -100,
                        "pending_change": 10,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -2000000000,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                    "crcat": {
                        "confirmed_wallet_balance": -90,
                        "spendable_balance": 10,
                        "max_send_amount": 10,
                        "pending_change": -10,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                post_block_balance_updates={
                    "crcat": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": 0,
                        "pending_change": 0,
                        "max_send_amount": 0,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 0,
                    }
                },
                post_block_additional_balance_info={
                    "crcat": {
                        "pending_approval_balance": 90,
                    },
                },
            ),
        ]
    )
    assert await wallet_node_1.wallet_state_manager.wallets[env_1.dealias_wallet_id("crcat")].match_hinted_coin(
        next(c for tx in txs for c in tx.additions if c.amount == 90), wallet_1_ph
    )
    pending_tx = await client_1.get_transactions(
        env_1.dealias_wallet_id("crcat"),
        0,
        1,
        reverse=True,
        type_filter=TransactionTypeFilter.include([TransactionType.INCOMING_CRCAT_PENDING]),
    )
    assert len(pending_tx) == 1

    # Send the VC to wallet_1 to use for the CR-CATs
    await client_0.vc_spend(
        vc_record.vc.launcher_id, wallet_environments.tx_config, new_puzhash=await wallet_1.get_new_puzzlehash()
    )
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": 1,
                    }
                },
                post_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    }
                },
            ),
            WalletStateTransition(
                post_block_balance_updates={
                    "vc": {"init": True, "set_remainder": True},
                }
            ),
        ]
    )
    await client_1.vc_add_proofs(proofs.key_value_pairs)

    # Claim the pending approval to our wallet
    await client_1.crcat_approve_pending(
        env_1.dealias_wallet_id("crcat"),
        uint64(90),
        wallet_environments.tx_config,
        fee=uint64(90),
    )
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -90,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -90,
                        "<=#max_send_amount": -90,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                    "crcat": {
                        "unconfirmed_wallet_balance": 90,
                        "pending_change": 90,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -90,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                    "crcat": {
                        "confirmed_wallet_balance": 90,
                        "spendable_balance": 90,
                        "max_send_amount": 90,
                        "pending_change": -90,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": -1,
                    },
                },
                post_block_additional_balance_info={
                    "crcat": {
                        "pending_approval_balance": 0,
                    },
                },
            ),
        ]
    )

    # (Negative test) Try to spend a CR-CAT that we don't have a valid VC for
    with pytest.raises(ValueError):
        await client_0.cat_spend(
            cr_cat_wallet_0.id(),
            wallet_environments.tx_config,
            uint64(10),
            wallet_1_addr,
        )

    # Test melting a CRCAT
    tx = (
        await client_1.cat_spend(
            env_1.dealias_wallet_id("crcat"),
            wallet_environments.tx_config,
            uint64(20),
            wallet_1_addr,
            uint64(0),
            cat_discrepancy=(-50, Program.to(None), Program.to(None)),
        )
    ).transaction
    [tx] = await wallet_node_1.wallet_state_manager.add_pending_transactions([tx])
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": 20,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": 20,
                        "<=#max_send_amount": 20,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                    "crcat": {
                        "unconfirmed_wallet_balance": -50,
                        "spendable_balance": -90,
                        "max_send_amount": -90,
                        "pending_change": 40,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 20,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "vc": {
                        "pending_coin_removal_count": -1,
                    },
                    "crcat": {
                        "confirmed_wallet_balance": -50,  # should go straight to confirmed because we sent to ourselves
                        "spendable_balance": 40,
                        "max_send_amount": 40,
                        "pending_change": -40,
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                    },
                },
            ),
        ]
    )
    vc_record_updated = await client_1.vc_get(vc_record_updated.vc.launcher_id)
    assert vc_record_updated is not None

    # Revoke VC
    await client_0.vc_revoke(vc_record_updated.vc.coin.parent_coin_info, wallet_environments.tx_config, uint64(1))
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        "set_remainder": True,
                    },
                    "did": {
                        "spendable_balance": -1,
                        "pending_change": 1,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        "pending_coin_removal_count": -1,
                        "set_remainder": True,
                    },
                    "did": {
                        "spendable_balance": 1,
                        "pending_change": -1,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                post_block_balance_updates={
                    "vc": {
                        "unspent_coin_count": -1,
                    },
                },
            ),
        ]
    )
    assert (
        len(await (await wallet_node_0.wallet_state_manager.get_or_create_vc_wallet()).store.get_unconfirmed_vcs()) == 0
    )


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
@pytest.mark.anyio
async def test_self_revoke(wallet_environments: WalletTestFramework) -> None:
    # Setup
    env_0: WalletEnvironment = wallet_environments.environments[0]
    wallet_node_0 = env_0.node
    wallet_0 = env_0.xch_wallet
    client_0 = env_0.rpc_client

    # Aliases
    env_0.wallet_aliases = {
        "xch": 1,
        "did": 2,
        "vc": 3,
    }

    # Generate DID as an "authorized provider"
    async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(1), action_scope
        )
    did_id: bytes32 = bytes32.from_hexstr(did_wallet.get_my_DID())

    vc_record = (
        await client_0.vc_mint(
            did_id, wallet_environments.tx_config, target_address=await wallet_0.get_new_puzzlehash(), fee=uint64(200)
        )
    ).vc_record
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                # Balance checking for this spend covered in test_vc_lifecycle
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"init": True, "set_remainder": True},
                    "vc": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "did": {"set_remainder": True},
                    "vc": {"set_remainder": True},
                },
            )
        ]
    )
    new_vc_record: Optional[VCRecord] = await client_0.vc_get(vc_record.vc.launcher_id)
    assert new_vc_record is not None

    # Test a negative case real quick (mostly unrelated)
    with pytest.raises(ValueError, match="at the same time"):
        async with wallet_node_0.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=False
        ) as action_scope:
            await (await wallet_node_0.wallet_state_manager.get_or_create_vc_wallet()).generate_signed_transaction(
                new_vc_record.vc.launcher_id,
                action_scope,
                new_proof_hash=bytes32([0] * 32),
                self_revoke=True,
            )

    # Send the DID to oblivion
    async with did_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await did_wallet.transfer_did(bytes32([0] * 32), uint64(0), False, action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "did": {"set_remainder": True},
                },
                post_block_balance_updates={},
            )
        ]
    )

    # Make sure revoking still works
    await client_0.vc_revoke(new_vc_record.vc.coin.parent_coin_info, wallet_environments.tx_config, uint64(0))
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                # Balance checking for this spend covered in test_vc_lifecycle
                pre_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "vc": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": -1,
                    },
                },
            )
        ]
    )
    vc_record_revoked: Optional[VCRecord] = await client_0.vc_get(vc_record.vc.launcher_id)
    assert vc_record_revoked is None
    assert (
        len(await (await wallet_node_0.wallet_state_manager.get_or_create_vc_wallet()).store.get_unconfirmed_vcs()) == 0
    )


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
@pytest.mark.anyio
async def test_cat_wallet_conversion(
    self_hostname: str,
    one_wallet_and_one_simulator_services: Any,
    trusted: Any,
) -> None:
    num_blocks = 1
    full_nodes, wallets, bt = one_wallet_and_one_simulator_services
    full_node_api: FullNodeSimulator = full_nodes[0]._api
    full_node_server = full_node_api.full_node.server
    wallet_service_0 = wallets[0]
    wallet_node_0 = wallet_service_0._node
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

    client_0 = await WalletRpcClient.create(
        bt.config["self_hostname"],
        wallet_service_0.rpc_server.listen_port,
        wallet_service_0.root_path,
        wallet_service_0.config,
    )

    if trusted:
        wallet_node_0.config["trusted_peers"] = {
            full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
        }
    else:
        wallet_node_0.config["trusted_peers"] = {}

    await wallet_node_0.server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    # Key point of test: create a normal CAT wallet first, and see if it gets converted to CR-CAT wallet
    await CATWallet.get_or_create_wallet_for_cat(
        wallet_node_0.wallet_state_manager, wallet_0, Program.to(None).get_tree_hash().hex()
    )

    did_id = bytes32([0] * 32)
    await mint_cr_cat(num_blocks, wallet_0, wallet_node_0, client_0, full_node_api, [did_id])
    await full_node_api.farm_blocks_to_wallet(count=num_blocks, wallet=wallet_0)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node_0, timeout=20)

    async def check_length(length: int, func: Callable[..., Awaitable[Any]], *args: Any) -> Optional[Literal[True]]:
        if len(await func(*args)) == length:
            return True
        return None  # pragma: no cover

    await time_out_assert_not_none(
        15, check_length, 1, wallet_node_0.wallet_state_manager.get_all_wallet_info_entries, WalletType.CRCAT
    )
    await time_out_assert_not_none(
        15, check_length, 0, wallet_node_0.wallet_state_manager.get_all_wallet_info_entries, WalletType.CAT
    )
