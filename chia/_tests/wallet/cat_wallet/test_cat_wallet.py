from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, TypeVar

import pytest
from chia_rs import CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.conftest import ConsensusMode
from chia._tests.environments.wallet import (
    NewPuzzleHashError,
    WalletEnvironment,
    WalletStateTransition,
    WalletTestFramework,
)
from chia._tests.util.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.simulator.simulator_protocol import ReorgProtocol
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import NIL, Program
from chia.types.coin_spend import make_spend
from chia.util.bech32m import encode_puzzle_hash
from chia.util.db_wrapper import DBWrapper2
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_info import LegacyCATInfo
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.r_cat_wallet import RCATWallet
from chia.wallet.conditions import CreateCoin, UnknownCondition
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import master_pk_to_wallet_pk_unhardened
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_hash_for_pk
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.vc_wallet.vc_drivers import create_revocation_layer
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_interested_store import WalletInterestedStore
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_request_types import GetTransactionMemo, PushTX
from chia.wallet.wallet_state_manager import WalletStateManager


def check_wallets(node: WalletNode) -> int:
    return len(node.wallet_state_manager.wallets.keys())


_T_CATWallet = TypeVar("_T_CATWallet", bound=CATWallet)


async def mint_cat(
    wallet_environments: WalletTestFramework,
    environment: WalletEnvironment,
    xch_alias: str,
    cat_alias: str,
    amount: uint64,
    wallet_type: type[_T_CATWallet],
    tail_nonce: str,
) -> _T_CATWallet:
    # (f (q . (() . tail_nonce)))
    tail = Program.to([5, (1, (None, tail_nonce))])
    tail_hash = tail.get_tree_hash()
    async with environment.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        inner_puzzle_hash = await action_scope.get_puzzle_hash(environment.wallet_state_manager)
        if wallet_type is RCATWallet:
            wrapped_inner_puzzle_hash = create_revocation_layer(bytes32.zeros, inner_puzzle_hash).get_tree_hash()
            extra_args: Any = (bytes32.zeros,)
        else:
            wrapped_inner_puzzle_hash = inner_puzzle_hash
            extra_args = tuple()
        eve_inner_puzzle = Program.to(
            (
                1,
                [
                    CreateCoin(wrapped_inner_puzzle_hash, amount, memos=[inner_puzzle_hash]).to_program(),
                    UnknownCondition(opcode=Program.to(51), args=[NIL, Program.to(-113), tail, NIL]).to_program(),
                ],
            )
        )
        eve_cat_puzzle = construct_cat_puzzle(
            CAT_MOD,
            tail_hash,
            eve_inner_puzzle,
        )
        eve_cat_puzzle_hash = eve_cat_puzzle.get_tree_hash()
        await environment.xch_wallet.generate_signed_transaction(
            amounts=[amount],
            puzzle_hashes=[eve_cat_puzzle_hash],
            action_scope=action_scope,
        )
        async with action_scope.use() as interface:
            cat_addition = next(
                addition
                for tx in interface.side_effects.transactions
                for addition in tx.additions
                if addition.puzzle_hash == eve_cat_puzzle_hash
            )
            interface.side_effects.extra_spends.append(
                unsigned_spend_bundle_for_spendable_cats(
                    CAT_MOD,
                    [
                        SpendableCAT(
                            cat_addition,
                            tail_hash,
                            eve_inner_puzzle,
                            NIL,
                        )
                    ],
                )
            )

    cat_wallet = await wallet_type.get_or_create_wallet_for_cat(
        environment.wallet_state_manager, environment.xch_wallet, tail_hash.hex(), *extra_args
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition()
            if env != environment
            else WalletStateTransition(
                pre_block_balance_updates={
                    xch_alias: {
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": -amount,
                        "<=#spendable_balance": -amount,
                        "<=#max_send_amount": -amount,
                        ">=#pending_change": 1,  # any amount increase
                        "pending_coin_removal_count": 1,
                    },
                    cat_alias: {
                        "init": True,
                    },
                },
                post_block_balance_updates={
                    xch_alias: {
                        "confirmed_wallet_balance": -amount,
                        "unconfirmed_wallet_balance": 0,
                        ">=#spendable_balance": 0,
                        ">=#max_send_amount": 0,
                        "<=#pending_change": 1,  # any amount decrease
                        "pending_coin_removal_count": -1,
                    },
                    cat_alias: {
                        "confirmed_wallet_balance": amount,
                        "unconfirmed_wallet_balance": amount,
                        "spendable_balance": amount,
                        "max_send_amount": amount,
                        "unspent_coin_count": 1,
                    },
                },
            )
            for env in wallet_environments.environments
        ]
    )

    return cat_wallet


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
@pytest.mark.limit_consensus_modes([ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_cat_creation(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    full_node_api = wallet_environments.full_node
    wsm = wallet_environments.environments[0].wallet_state_manager
    wallet = wallet_environments.environments[0].xch_wallet
    wallet_node = wallet_environments.environments[0].node
    wallet_environments.environments[0].wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }
    test_amount = uint64(100)

    cat_wallet = await mint_cat(
        wallet_environments,
        wallet_environments.environments[0],
        "xch",
        "cat",
        test_amount,
        wallet_type,
        "cat wallet",
    )

    # The next 2 lines are basically a noop, it just adds test coverage
    cat_wallet = await wallet_type.create(wsm, wallet, cat_wallet.wallet_info)
    await wsm.add_new_wallet(cat_wallet)

    if wallet_type is CATWallet:
        # Test migration
        all_lineage = await cat_wallet.lineage_store.get_all_lineage_proofs()
        current_info = cat_wallet.wallet_info
        data_str = bytes(
            LegacyCATInfo(
                cat_wallet.cat_info.limitations_program_hash, cat_wallet.cat_info.my_tail, list(all_lineage.items())
            )
        ).hex()
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        new_cat_wallet = await wallet_type.create(wsm, wallet, wallet_info)
        assert new_cat_wallet.cat_info.limitations_program_hash == cat_wallet.cat_info.limitations_program_hash
        assert new_cat_wallet.cat_info.my_tail == cat_wallet.cat_info.my_tail
        assert await cat_wallet.lineage_store.get_all_lineage_proofs() == all_lineage

        height = full_node_api.full_node.blockchain.get_peak_height()
        assert height is not None
        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32(32 * b"1"), None)
        )
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, peak_height=uint32(height + 1))
        # The "set_remainder" sections here are due to a peculiarity with how the creation method creates an incoming TX
        # The creation method is for testing purposes only so we're not going to bother fixing it for any real reason
        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": test_amount,
                            "unconfirmed_wallet_balance": 0,
                            "<=#spendable_balance": 1,
                            "<=#max_send_amount": 1,
                            ">=#pending_change": 1,  # any amount increase
                            "pending_coin_removal_count": 1,
                        },
                        "cat": {
                            "confirmed_wallet_balance": -test_amount,
                            "spendable_balance": -test_amount,
                            "max_send_amount": -test_amount,
                            "unspent_coin_count": -1,
                            "set_remainder": True,
                        },
                    },
                    post_block_balance_updates={
                        "xch": {
                            "confirmed_wallet_balance": -test_amount,
                            "unconfirmed_wallet_balance": 0,
                            ">=#spendable_balance": 0,
                            ">=#max_send_amount": 0,
                            "<=#pending_change": 1,  # any amount decrease
                            "pending_coin_removal_count": -1,
                        },
                        "cat": {
                            "confirmed_wallet_balance": test_amount,
                            "spendable_balance": test_amount,
                            "max_send_amount": test_amount,
                            "unspent_coin_count": 1,
                            "set_remainder": True,
                        },
                    },
                ),
            ]
        )


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "reuse_puzhash": True,  # irrelevant
            "trusted": True,  # irrelevant
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes([ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_cat_creation_unique_lineage_store(
    wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]
) -> None:
    wallet_environments.environments[0].wallet_aliases = {
        "xch": 1,
        "cat1": 2,
        "cat2": 3,
    }

    cat_wallet_1 = await mint_cat(
        wallet_environments,
        wallet_environments.environments[0],
        "xch",
        "cat1",
        uint64(100),
        wallet_type,
        "cat wallet 1",
    )
    cat_wallet_2 = await mint_cat(
        wallet_environments,
        wallet_environments.environments[0],
        "xch",
        "cat2",
        uint64(200),
        wallet_type,
        "cat wallet 2",
    )

    proofs_1 = await cat_wallet_1.lineage_store.get_all_lineage_proofs()
    proofs_2 = await cat_wallet_2.lineage_store.get_all_lineage_proofs()
    assert len(proofs_1) == len(proofs_2)
    assert proofs_1 != proofs_2
    assert cat_wallet_1.lineage_store.table_name != cat_wallet_2.lineage_store.table_name


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
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
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_cat_spend(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    # Setup
    env_1: WalletEnvironment = wallet_environments.environments[0]
    env_2: WalletEnvironment = wallet_environments.environments[1]
    wallet_node = env_1.node
    wallet_node_2 = env_2.node
    wallet2 = env_2.xch_wallet
    full_node_api = wallet_environments.full_node

    env_1.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }
    env_2.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    cat_wallet = await mint_cat(wallet_environments, env_1, "xch", "cat", uint64(100), wallet_type, "cat wallet")

    assert cat_wallet.cat_info.limitations_program_hash is not None
    asset_id = cat_wallet.get_asset_id()

    if wallet_type is RCATWallet:
        extra_args: Any = (bytes32.zeros,)
    else:
        extra_args = tuple()
    cat_wallet_2 = await wallet_type.get_or_create_wallet_for_cat(
        wallet_node_2.wallet_state_manager, wallet2, asset_id, *extra_args
    )

    assert cat_wallet.cat_info.limitations_program_hash == cat_wallet_2.cat_info.limitations_program_hash

    async with cat_wallet_2.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_2_hash = await action_scope.get_puzzle_hash(cat_wallet_2.wallet_state_manager)
    async with cat_wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet.generate_signed_transaction([uint64(60)], [cat_2_hash], action_scope, fee=uint64(1))
    tx_id = None
    for tx_record in action_scope.side_effects.transactions:
        if tx_record.wallet_id == cat_wallet.id():
            assert tx_record.to_puzzle_hash == cat_2_hash
        if tx_record.spend_bundle is not None:
            tx_id = tx_record.name
    assert tx_id is not None
    memos = await env_1.rpc_client.get_transaction_memo(GetTransactionMemo(transaction_id=tx_id))
    assert len(memos.coins_with_memos) == 2
    assert cat_2_hash in {coin_w_memos.memos[0] for coin_w_memos in memos.coins_with_memos}

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                    "cat": {
                        "unconfirmed_wallet_balance": -60,
                        "spendable_balance": -100,
                        "max_send_amount": -100,
                        "pending_change": 40,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": -60,
                        "spendable_balance": 40,
                        "max_send_amount": 40,
                        "pending_change": -40,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
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
                    "cat": {
                        "confirmed_wallet_balance": 60,
                        "unconfirmed_wallet_balance": 60,
                        "spendable_balance": 60,
                        "max_send_amount": 60,
                        "pending_change": 0,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": 0,
                    },
                },
            ),
        ]
    )

    async with cat_wallet_2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        coins = await cat_wallet_2.select_coins(uint64(60), action_scope)
    assert len(coins) == 1
    coin = coins.pop()
    tx_id = coin.name()
    memos = await env_2.rpc_client.get_transaction_memo(GetTransactionMemo(transaction_id=tx_id))
    assert len(memos.coins_with_memos) == 2
    assert cat_2_hash in {coin_w_memos.memos[0] for coin_w_memos in memos.coins_with_memos}
    async with cat_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_hash = await action_scope.get_puzzle_hash(cat_wallet.wallet_state_manager)
    async with cat_wallet_2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_2.generate_signed_transaction([uint64(15)], [cat_hash], action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": 15,
                        "unconfirmed_wallet_balance": 15,
                        "pending_coin_removal_count": 0,
                        "spendable_balance": 15,
                        "max_send_amount": 15,
                        "pending_change": 0,
                        "unspent_coin_count": 1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": -15,
                        "spendable_balance": -60,
                        "pending_change": 45,
                        "max_send_amount": -60,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": -15,
                        "pending_coin_removal_count": -1,
                        "spendable_balance": 45,
                        "max_send_amount": 45,
                        "pending_change": -45,
                        "unspent_coin_count": 0,
                    },
                },
            ),
        ]
    )

    height = full_node_api.full_node.blockchain.get_peak_height()
    assert height is not None
    await full_node_api.reorg_from_index_to_new_index(
        ReorgProtocol(uint32(height - 1), uint32(height + 1), bytes32(32 * b"1"), None)
    )
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, peak_height=uint32(height + 1))
    await env_1.change_balances(
        {
            "cat": {
                "confirmed_wallet_balance": -15,
                "unconfirmed_wallet_balance": -15,
                "pending_coin_removal_count": 0,
                "spendable_balance": -15,
                "max_send_amount": -15,
                "pending_change": 0,
                "unspent_coin_count": -1,
            },
        }
    )
    await env_1.check_balances()


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "reuse_puzhash": True,  # irrelevant
            "trusted": True,  # irrelevant
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_get_wallet_for_asset_id(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    wsm = wallet_environments.environments[0].wallet_state_manager
    wallet = wallet_environments.environments[0].xch_wallet

    wallet_environments.environments[0].wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    cat_wallet = await mint_cat(
        wallet_environments, wallet_environments.environments[0], "xch", "cat", uint64(100), wallet_type, "cat wallet"
    )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"init": True, "set_remainder": True},
                },
                post_block_balance_updates={
                    "xch": {"set_remainder": True},
                    "cat": {"set_remainder": True},
                },
            ),
        ]
    )

    asset_id = cat_wallet.get_asset_id()
    assert await wsm.get_wallet_for_asset_id(asset_id) == cat_wallet

    # Test that the a default CAT will initialize correctly
    asset = DEFAULT_CATS[next(iter(DEFAULT_CATS))]
    asset_id = asset["asset_id"]
    if wallet_type is RCATWallet:
        extra_args: Any = (bytes32.zeros,)
    else:
        extra_args = tuple()
    cat_wallet_2 = await wallet_type.get_or_create_wallet_for_cat(wsm, wallet, asset_id, *extra_args)
    assert cat_wallet_2.get_name() == asset["name"]
    await cat_wallet_2.set_name("Test Name")
    assert cat_wallet_2.get_name() == "Test Name"


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "blocks_needed": [1, 1],
            "reuse_puzhash": True,
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_cat_doesnt_see_eve(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    # Setup
    env_1: WalletEnvironment = wallet_environments.environments[0]
    env_2: WalletEnvironment = wallet_environments.environments[1]
    wallet_node_2 = env_2.node
    wallet = env_1.xch_wallet
    wallet2 = env_2.xch_wallet

    env_1.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }
    env_2.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    cat_wallet = await mint_cat(wallet_environments, env_1, "xch", "cat", uint64(100), wallet_type, "cat wallet")

    assert cat_wallet.cat_info.limitations_program_hash is not None
    asset_id = cat_wallet.get_asset_id()

    if wallet_type is RCATWallet:
        extra_args: Any = (bytes32.zeros,)
    else:
        extra_args = tuple()
    cat_wallet_2 = await wallet_type.get_or_create_wallet_for_cat(
        wallet_node_2.wallet_state_manager, wallet2, asset_id, *extra_args
    )

    assert cat_wallet.cat_info.limitations_program_hash == cat_wallet_2.cat_info.limitations_program_hash

    async with cat_wallet_2.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_2_hash = await action_scope.get_puzzle_hash(cat_wallet_2.wallet_state_manager)
    async with cat_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await cat_wallet.generate_signed_transaction([uint64(60)], [cat_2_hash], action_scope, fee=uint64(1))

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -1,
                        "<=#spendable_balance": -1,
                        "<=#max_send_amount": -1,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                    "cat": {
                        "unconfirmed_wallet_balance": -60,
                        "spendable_balance": -100,
                        "max_send_amount": -100,
                        "pending_change": 40,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -1,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": -60,
                        "spendable_balance": 40,
                        "max_send_amount": 40,
                        "pending_change": -40,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
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
                    "cat": {
                        "confirmed_wallet_balance": 60,
                        "unconfirmed_wallet_balance": 60,
                        "spendable_balance": 60,
                        "max_send_amount": 60,
                        "pending_change": 0,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": 0,
                    },
                },
            ),
        ]
    )

    cc2_ph = await cat_wallet_2.get_cat_puzzle_hash(new=False)
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await wallet.wallet_state_manager.main_wallet.generate_signed_transaction([uint64(10)], [cc2_ph], action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -10,
                        "<=#spendable_balance": -10,
                        "<=#max_send_amount": -10,
                        ">=#pending_change": 1,  # any amount increase
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -10,
                        ">=#spendable_balance": 1,  # any amount increase
                        ">=#max_send_amount": 1,  # any amount increase
                        "<=#pending_change": -1,  # any amount decrease
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            # No state changes should occur since this was an unspent eve CAT
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={},
            ),
        ]
    )

    id = cat_wallet_2.id()
    wsm = cat_wallet_2.wallet_state_manager

    async def query_and_assert_transactions(wsm: WalletStateManager, id: uint32) -> int:
        all_txs = await wsm.tx_store.get_all_transactions_for_wallet(id)
        return len(list(filter(lambda tx: tx.amount == 10, all_txs)))

    await time_out_assert(20, query_and_assert_transactions, 0, wsm, id)


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 3,
            "blocks_needed": [1, 1, 1],
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_cat_spend_multiple(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    # Setup
    env_0: WalletEnvironment = wallet_environments.environments[0]
    env_1: WalletEnvironment = wallet_environments.environments[1]
    env_2: WalletEnvironment = wallet_environments.environments[2]
    wallet_node_1 = env_1.node
    wallet_node_2 = env_2.node
    wallet_1 = env_1.xch_wallet
    wallet_2 = env_2.xch_wallet

    env_0.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }
    env_1.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }
    env_2.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    cat_wallet_0 = await mint_cat(wallet_environments, env_0, "xch", "cat", uint64(100), wallet_type, "cat wallet")

    assert cat_wallet_0.cat_info.limitations_program_hash is not None
    asset_id = cat_wallet_0.get_asset_id()

    if wallet_type is RCATWallet:
        extra_args: Any = (bytes32.zeros,)
    else:
        extra_args = tuple()

    cat_wallet_1 = await wallet_type.get_or_create_wallet_for_cat(
        wallet_node_1.wallet_state_manager, wallet_1, asset_id, *extra_args
    )

    cat_wallet_2 = await wallet_type.get_or_create_wallet_for_cat(
        wallet_node_2.wallet_state_manager, wallet_2, asset_id, *extra_args
    )

    assert cat_wallet_0.cat_info.limitations_program_hash == cat_wallet_1.cat_info.limitations_program_hash
    assert cat_wallet_0.cat_info.limitations_program_hash == cat_wallet_2.cat_info.limitations_program_hash

    async with cat_wallet_1.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_1_hash = await action_scope.get_puzzle_hash(cat_wallet_1.wallet_state_manager)
    async with cat_wallet_2.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_2_hash = await action_scope.get_puzzle_hash(cat_wallet_2.wallet_state_manager)
    async with cat_wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_0.generate_signed_transaction([uint64(60), uint64(20)], [cat_1_hash, cat_2_hash], action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": -80,
                        "spendable_balance": -100,
                        "max_send_amount": -100,
                        "pending_change": 20,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": -80,
                        "spendable_balance": 20,
                        "max_send_amount": 20,
                        "pending_change": -20,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
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
                    "cat": {
                        "confirmed_wallet_balance": 60,
                        "unconfirmed_wallet_balance": 60,
                        "spendable_balance": 60,
                        "max_send_amount": 60,
                        "pending_change": 0,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": 0,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
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
                    "cat": {
                        "confirmed_wallet_balance": 20,
                        "unconfirmed_wallet_balance": 20,
                        "spendable_balance": 20,
                        "max_send_amount": 20,
                        "pending_change": 0,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": 0,
                    },
                },
            ),
        ]
    )

    async with cat_wallet_0.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_hash = await action_scope.get_puzzle_hash(cat_wallet_0.wallet_state_manager)
    async with cat_wallet_1.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await cat_wallet_1.generate_signed_transaction([uint64(15)], [cat_hash], action_scope)

    async with cat_wallet_2.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope_2:
        await cat_wallet_2.generate_signed_transaction([uint64(20)], [cat_hash], action_scope_2)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {},
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": 35,
                        "unconfirmed_wallet_balance": 35,
                        "spendable_balance": 35,
                        "max_send_amount": 35,
                        "pending_change": 0,
                        "unspent_coin_count": 2,
                        "pending_coin_removal_count": 0,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": -15,
                        "spendable_balance": -60,
                        "pending_change": 45,
                        "max_send_amount": -60,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": -15,
                        "spendable_balance": 45,
                        "pending_change": -45,
                        "max_send_amount": 45,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": -20,
                        "spendable_balance": -20,
                        "pending_change": 0,
                        "max_send_amount": -20,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": -20,
                        "spendable_balance": 0,
                        "pending_change": 0,
                        "max_send_amount": 0,
                        "unspent_coin_count": -1,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )

    # Test with Memo
    async with cat_wallet_1.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await cat_wallet_1.generate_signed_transaction(
            [uint64(30)], [cat_hash], action_scope, memos=[[b"Markus Walburg"]]
        )
    with pytest.raises(ValueError):
        async with cat_wallet_1.wallet_state_manager.new_action_scope(
            DEFAULT_TX_CONFIG, push=False
        ) as failed_action_scope:
            await cat_wallet_1.generate_signed_transaction(
                [uint64(30)],
                [cat_hash],
                failed_action_scope,
                memos=[[b"too"], [b"many"], [b"memos"]],
            )

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {},
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": 30,
                        "unconfirmed_wallet_balance": 30,
                        "spendable_balance": 30,
                        "max_send_amount": 30,
                        "pending_change": 0,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": 0,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": -30,
                        "spendable_balance": -45,
                        "pending_change": 15,
                        "max_send_amount": -45,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": -30,
                        "spendable_balance": 15,
                        "pending_change": -15,
                        "max_send_amount": 15,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={},
            ),
        ]
    )

    txs = await wallet_1.wallet_state_manager.tx_store.get_transactions_between(cat_wallet_1.id(), 0, 100000)
    for tx in txs:
        if tx.amount == 30:
            assert len(tx.memos) == 2  # One for tx, one for change
            assert b"Markus Walburg" in [v for v_list in tx.memos.values() for v in v_list]
            assert tx.spend_bundle is not None
            assert next(iter(tx.memos.keys())) in [a.name() for a in tx.spend_bundle.additions()]


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "reuse_puzhash": True,  # irrelevant
            "trusted": True,  # irrelevant
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_cat_max_amount_send(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    # Setup
    env: WalletEnvironment = wallet_environments.environments[0]

    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    cat_wallet = await mint_cat(wallet_environments, env, "xch", "cat", uint64(100000), wallet_type, "cat wallet")

    assert cat_wallet.cat_info.limitations_program_hash is not None

    async with cat_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_2 = await action_scope.get_puzzle(cat_wallet.wallet_state_manager)
        cat_2_hash = cat_2.get_tree_hash()
        amounts = []
        puzzle_hashes = []
        for i in range(1, 50):
            amounts.append(uint64(i))
            puzzle_hashes.append(cat_2_hash)
        spent_coin = (await cat_wallet.get_cat_spendable_coins())[0].coin
        await cat_wallet.generate_signed_transaction(amounts, puzzle_hashes, action_scope, coins={spent_coin})

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": 0,
                        "spendable_balance": -100000,
                        "max_send_amount": -100000,
                        "pending_change": 100000,
                        "pending_coin_removal_count": 1,
                        "unspent_coin_count": 0,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": 0,
                        "spendable_balance": 100000,
                        "max_send_amount": 100000,
                        "pending_change": -100000,
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 49,
                    },
                },
            )
        ]
    )

    async def check_all_there() -> bool:
        spendable = await cat_wallet.get_cat_spendable_coins()
        spendable_name_set = set()
        for record in spendable:
            spendable_name_set.add(record.coin.name())
        if wallet_type is RCATWallet:
            inner_puzzle = create_revocation_layer(bytes32.zeros, cat_2_hash)
        else:
            inner_puzzle = cat_2
        puzzle_hash = construct_cat_puzzle(
            CAT_MOD, cat_wallet.cat_info.limitations_program_hash, inner_puzzle
        ).get_tree_hash()
        for i in range(1, 50):
            coin = Coin(spent_coin.name(), puzzle_hash, uint64(i))
            if coin.name() not in spendable_name_set:
                return False
        return True

    await time_out_assert(20, check_all_there, True)
    max_sent_amount = await cat_wallet.get_max_send_amount()

    # 1) Generate transaction that is under the limit
    async with cat_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        await cat_wallet.generate_signed_transaction([uint64(max_sent_amount - 1)], [bytes32.zeros], action_scope)
    assert action_scope.side_effects.transactions[0].amount == uint64(max_sent_amount - 1)

    # 2) Generate transaction that is equal to limit
    async with cat_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        await cat_wallet.generate_signed_transaction([uint64(max_sent_amount)], [bytes32.zeros], action_scope)
    assert action_scope.side_effects.transactions[0].amount == uint64(max_sent_amount)

    # 3) Generate transaction that is greater than limit
    with pytest.raises(ValueError, match="Can't select amount higher than our spendable balance."):
        async with cat_wallet.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=False
        ) as action_scope:
            await cat_wallet.generate_signed_transaction([uint64(max_sent_amount + 1)], [bytes32.zeros], action_scope)


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 2,
            "blocks_needed": [1, 1],
            "config_overrides": {"automatically_add_unknown_cats": True},
        },
        {
            "num_environments": 2,
            "blocks_needed": [1, 1],
            "config_overrides": {"automatically_add_unknown_cats": False},
        },
    ],
    indirect=True,
)
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_cat_hint(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    # Setup
    env_1: WalletEnvironment = wallet_environments.environments[0]
    env_2: WalletEnvironment = wallet_environments.environments[1]
    wallet_node_1 = env_1.node
    wallet_node_2 = env_2.node
    wallet_1 = env_1.xch_wallet
    wallet_2 = env_2.xch_wallet

    env_1.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }
    env_2.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    autodiscovery = wallet_node_1.config["automatically_add_unknown_cats"]

    cat_wallet = await mint_cat(wallet_environments, env_1, "xch", "cat", uint64(100), wallet_type, "cat wallet")

    assert cat_wallet.cat_info.limitations_program_hash is not None

    async with wallet_2.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        cat_2_hash = await action_scope.get_puzzle_hash(wallet_2.wallet_state_manager)
    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await cat_wallet.generate_signed_transaction([uint64(60)], [cat_2_hash], action_scope, memos=[[cat_2_hash]])

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": -60,
                        "spendable_balance": -100,
                        "max_send_amount": -100,
                        "pending_change": 40,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": -60,
                        "spendable_balance": 40,
                        "max_send_amount": 40,
                        "pending_change": -40,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates=(
                    {
                        "cat": {
                            "init": True,
                            "confirmed_wallet_balance": 60,
                            "unconfirmed_wallet_balance": 60,
                            "spendable_balance": 60,
                            "max_send_amount": 60,
                            "pending_change": 0,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": 0,
                        },
                    }
                    if autodiscovery
                    else {}
                ),
            ),
        ]
    )

    # Then we update the wallet's default CATs
    wallet_node_2.wallet_state_manager.default_cats = {
        cat_wallet.cat_info.limitations_program_hash.hex(): {
            "asset_id": cat_wallet.cat_info.limitations_program_hash.hex(),
            "name": "Test",
            "symbol": "TST",
        }
    }

    # Then we send another transaction
    async with wallet_1.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        await cat_wallet.generate_signed_transaction([uint64(10)], [cat_2_hash], action_scope, memos=[[cat_2_hash]])

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": -10,
                        "spendable_balance": -40,
                        "max_send_amount": -40,
                        "pending_change": 30,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": -10,
                        "spendable_balance": 30,
                        "max_send_amount": 30,
                        "pending_change": -30,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates=(
                    {
                        "cat": {
                            "confirmed_wallet_balance": 10,
                            "unconfirmed_wallet_balance": 10,
                            "spendable_balance": 10,
                            "max_send_amount": 10,
                            "pending_change": 0,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": 0,
                        },
                    }
                    if autodiscovery
                    else {
                        "cat": {
                            "init": True,
                            "confirmed_wallet_balance": 70,
                            "unconfirmed_wallet_balance": 70,
                            "spendable_balance": 70,
                            "max_send_amount": 70,
                            "pending_change": 0,
                            "unspent_coin_count": 2,
                            "pending_coin_removal_count": 0,
                        }
                    }
                ),
            ),
        ]
    )

    cat_wallet_2 = wallet_node_2.wallet_state_manager.wallets[uint32(2)]
    assert isinstance(cat_wallet_2, CATWallet)

    async with cat_wallet.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        cat_hash = await action_scope.get_puzzle_hash(cat_wallet.wallet_state_manager)
    async with cat_wallet_2.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True
    ) as action_scope:
        await cat_wallet_2.generate_signed_transaction([uint64(5)], [cat_hash], action_scope)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {},
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": 5,
                        "unconfirmed_wallet_balance": 5,
                        "spendable_balance": 5,
                        "max_send_amount": 5,
                        "pending_change": 0,
                        "unspent_coin_count": 1,
                        "pending_coin_removal_count": 0,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": -5,
                        "<=#spendable_balance": -5,
                        "<=#max_send_amount": -5,
                        ">=#pending_change": 1,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 1,
                    },
                },
                post_block_balance_updates={
                    "cat": {
                        "confirmed_wallet_balance": -5,
                        ">=#spendable_balance": 1,
                        ">=#max_send_amount": 1,
                        "<=#pending_change": -1,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
        ]
    )


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "config_overrides": {"automatically_add_unknown_cats": True},
        },
    ],
    indirect=True,
)
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.anyio
async def test_cat_change_detection(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    full_node_api = wallet_environments.full_node
    env = wallet_environments.environments[0]
    wsm = env.wallet_state_manager
    wallet = env.xch_wallet

    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    # Mint CAT to ourselves, immediately spend it to an unhinted puzzle hash that we have manually added to the DB
    # We should pick up this coin as balance even though it is unhinted because it is "change"
    pubkey_unhardened = master_pk_to_wallet_pk_unhardened(wsm.root_pubkey, uint32(100000000))
    inner_puzhash = puzzle_hash_for_pk(pubkey_unhardened)
    if wallet_type is RCATWallet:
        inner_puzhash = create_revocation_layer(bytes32.zeros, inner_puzhash).get_tree_hash()
    puzzlehash_unhardened = construct_cat_puzzle(
        CAT_MOD, Program.to(None).get_tree_hash(), inner_puzhash
    ).get_tree_hash_precalc(inner_puzhash)
    change_derivation = DerivationRecord(
        uint32(0), puzzlehash_unhardened, pubkey_unhardened, WalletType.CAT, uint32(2), False
    )
    # Insert the derivation record before the wallet exists so that it is not subscribed to
    await wsm.puzzle_store.add_derivation_paths([change_derivation])
    async with wallet.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        our_puzzle = await action_scope.get_puzzle(wallet.wallet_state_manager)
    cat_puzzle = construct_cat_puzzle(
        CAT_MOD,
        Program.to(None).get_tree_hash(),
        Program.to(1),
    )
    addr = encode_puzzle_hash(cat_puzzle.get_tree_hash(), "txch")
    cat_amount_0 = uint64(100)
    cat_amount_1 = uint64(5)

    tx = (await env.rpc_client.send_transaction(1, cat_amount_0, addr, wallet_environments.tx_config)).transaction
    spend_bundle = tx.spend_bundle
    assert spend_bundle is not None

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={"xch": {"set_remainder": True}},
                post_block_balance_updates={"xch": {"set_remainder": True}},
            )
        ]
    )

    # Do the eve spend back to our wallet and add the CR layer
    cat_coin = next(c for c in spend_bundle.additions() if c.amount == cat_amount_0)
    next_coin = Coin(
        cat_coin.name(),
        construct_cat_puzzle(CAT_MOD, Program.to(None).get_tree_hash(), our_puzzle).get_tree_hash(),
        cat_amount_0,
    )
    eve_spend, _ = await wsm.sign_bundle(
        [
            make_spend(
                cat_coin,
                cat_puzzle,
                Program.to(
                    [
                        Program.to(
                            [
                                [51, our_puzzle.get_tree_hash(), cat_amount_0, [our_puzzle.get_tree_hash()]],
                                [51, None, -113, None, None],
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
            ),
            make_spend(
                next_coin,
                construct_cat_puzzle(CAT_MOD, Program.to(None).get_tree_hash(), our_puzzle),
                Program.to(
                    [
                        [
                            None,
                            (
                                1,
                                [
                                    [51, inner_puzhash, cat_amount_1],
                                    [51, bytes32.zeros, cat_amount_0 - cat_amount_1],
                                ],
                            ),
                            None,
                        ],
                        LineageProof(
                            cat_coin.parent_coin_info, Program.to(1).get_tree_hash(), cat_amount_0
                        ).to_program(),
                        next_coin.name(),
                        coin_as_list(next_coin),
                        [next_coin.parent_coin_info, our_puzzle.get_tree_hash(), next_coin.amount],
                        0,
                        0,
                    ]
                ),
            ),
        ],
    )
    await env.rpc_client.push_tx(PushTX(eve_spend))
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, eve_spend.name())
    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "cat": {
                        "init": True,
                        "confirmed_wallet_balance": 5,
                        "unconfirmed_wallet_balance": 5,
                        "spendable_balance": 5,
                        "max_send_amount": 5,
                        "unspent_coin_count": 1,
                    }
                },
            )
        ]
    )

    assert not full_node_api.full_node.subscriptions.has_puzzle_subscription(puzzlehash_unhardened)


@pytest.mark.anyio
async def test_unacknowledged_cat_table() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        db_name = Path(temporary_directory).joinpath("test.sqlite")
        db_name.parent.mkdir(parents=True, exist_ok=True)
        async with DBWrapper2.managed(database=db_name) as db_wrapper:
            interested_store = await WalletInterestedStore.create(db_wrapper)

            def asset_id(i: int) -> bytes32:
                return bytes32([i] * 32)

            def coin_state(i: int) -> CoinState:
                return CoinState(Coin(bytes32.zeros, bytes32.zeros, uint64(i)), None, None)

            await interested_store.add_unacknowledged_coin_state(asset_id(0), coin_state(0), None)
            await interested_store.add_unacknowledged_coin_state(asset_id(1), coin_state(1), 100)
            assert await interested_store.get_unacknowledged_states_for_asset_id(asset_id(0)) == [(coin_state(0), 0)]
            await interested_store.add_unacknowledged_coin_state(asset_id(0), coin_state(0), None)
            assert await interested_store.get_unacknowledged_states_for_asset_id(asset_id(0)) == [(coin_state(0), 0)]
            assert await interested_store.get_unacknowledged_states_for_asset_id(asset_id(1)) == [(coin_state(1), 100)]
            assert await interested_store.get_unacknowledged_states_for_asset_id(asset_id(2)) == []
            await interested_store.rollback_to_block(50)
            assert await interested_store.get_unacknowledged_states_for_asset_id(asset_id(1)) == []
            await interested_store.delete_unacknowledged_states_for_asset_id(asset_id(1))
            assert await interested_store.get_unacknowledged_states_for_asset_id(asset_id(0)) == [(coin_state(0), 0)]
            await interested_store.delete_unacknowledged_states_for_asset_id(asset_id(0))
            assert await interested_store.get_unacknowledged_states_for_asset_id(asset_id(0)) == []


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "reuse_puzhash": True,  # Parameter doesn't matter for this test
            "config_overrides": {"automatically_add_unknown_cats": True},
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes([ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.anyio
async def test_cat_melt_balance(wallet_environments: WalletTestFramework) -> None:
    # We push spend bundles direct to full node in this test because
    # we are testing correct observance independent of local state
    env = wallet_environments.environments[0]
    wallet = env.xch_wallet
    simulator = wallet_environments.full_node

    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    ACS = Program.to(1)
    ACS_TAIL = Program.to([])
    ACS_TAIL_HASH = ACS_TAIL.get_tree_hash()
    CAT_w_ACS = construct_cat_puzzle(CAT_MOD, ACS_TAIL_HASH, ACS)
    CAT_w_ACS_HASH = CAT_w_ACS.get_tree_hash()

    from chia.simulator.simulator_protocol import GetAllCoinsProtocol
    from chia.wallet.cat_wallet.cat_utils import SpendableCAT, unsigned_spend_bundle_for_spendable_cats
    from chia.wallet.conditions import CreateCoin, UnknownCondition

    await simulator.farm_blocks_to_puzzlehash(count=1, farm_to=CAT_w_ACS_HASH, guarantee_transaction_blocks=True)
    await simulator.farm_blocks_to_puzzlehash(count=1)
    cat_coin = next(
        c.coin
        for c in await simulator.get_all_coins(GetAllCoinsProtocol(include_spent_coins=False))
        if c.coin.puzzle_hash == CAT_w_ACS_HASH
    )

    tx_amount = 10

    async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
        wallet_ph = await action_scope.get_puzzle_hash(env.wallet_state_manager)
        spend_to_wallet = unsigned_spend_bundle_for_spendable_cats(
            CAT_MOD,
            [
                SpendableCAT(
                    coin=cat_coin,
                    limitations_program_hash=ACS_TAIL_HASH,
                    inner_puzzle=ACS,
                    inner_solution=Program.to(
                        [[51, wallet_ph, tx_amount, [wallet_ph]], [51, None, -113, ACS_TAIL, None]]
                    ),
                    extra_delta=tx_amount - cat_coin.amount,
                )
            ],
        )
    await env.rpc_client.push_tx(PushTX(spend_to_wallet))
    await time_out_assert(10, simulator.tx_id_in_mempool, True, spend_to_wallet.name())

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={},
                post_block_balance_updates={
                    "xch": {},
                    "cat": {
                        "init": True,
                        "confirmed_wallet_balance": tx_amount,
                        "unconfirmed_wallet_balance": tx_amount,
                        "spendable_balance": tx_amount,
                        "max_send_amount": tx_amount,
                        "unspent_coin_count": 1,
                    },
                },
            )
        ]
    )

    cat_wallet = env.wallet_state_manager.wallets[uint32(2)]
    assert isinstance(cat_wallet, CATWallet)

    # Let's test that continuing to melt this CAT results in the correct balance changes
    for _ in range(5):
        tx_amount -= 1
        new_coin = (await cat_wallet.get_cat_spendable_coins())[0].coin
        new_spend = unsigned_spend_bundle_for_spendable_cats(
            CAT_MOD,
            [
                SpendableCAT(
                    coin=new_coin,
                    limitations_program_hash=ACS_TAIL_HASH,
                    inner_puzzle=await cat_wallet.inner_puzzle_for_cat_puzhash(new_coin.puzzle_hash),
                    inner_solution=wallet.make_solution(
                        primaries=[CreateCoin(wallet_ph, uint64(tx_amount), [wallet_ph])],
                        conditions=(
                            UnknownCondition(
                                opcode=Program.to(51),
                                args=[Program.to(None), Program.to(-113), Program.to(ACS_TAIL), Program.to(None)],
                            ),
                        ),
                    ),
                    extra_delta=-1,
                )
            ],
        )
        signed_spend, _ = await env.wallet_state_manager.sign_bundle(new_spend.coin_spends)
        await env.rpc_client.push_tx(PushTX(signed_spend))
        await time_out_assert(10, simulator.tx_id_in_mempool, True, signed_spend.name())

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={},
                    post_block_balance_updates={
                        "xch": {},
                        "cat": {
                            "confirmed_wallet_balance": -1,
                            "unconfirmed_wallet_balance": -1,
                            "spendable_balance": -1,
                            "max_send_amount": -1,
                        },
                    },
                )
            ]
        )


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
            "trusted": True,  # Parameter doesn't matter for this test
            "reuse_puzhash": True,  # Important to test this is ignored in the duplicate change scenario
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize("wallet_type", [CATWallet, RCATWallet])
@pytest.mark.limit_consensus_modes([ConsensusMode.PLAIN], reason="irrelevant")
@pytest.mark.anyio
async def test_cat_puzzle_hashes(wallet_environments: WalletTestFramework, wallet_type: type[CATWallet]) -> None:
    env = wallet_environments.environments[0]

    env.wallet_aliases = {
        "xch": 1,
        "cat": 2,
    }

    cat_wallet = await mint_cat(wallet_environments, env, "xch", "cat", uint64(100), wallet_type, "cat wallet")

    # Test that we attempt a new puzzle hash here even though everything says we shouldn't
    with pytest.raises(NewPuzzleHashError):
        async with env.wallet_state_manager.new_action_scope(wallet_environments.tx_config, push=True) as action_scope:
            await cat_wallet.generate_signed_transaction(
                [uint64(50)],
                [await action_scope.get_puzzle_hash(cat_wallet.wallet_state_manager)],
                action_scope,
            )

    # Test new puzzle hash getting
    current_derivation_index = await env.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
        uint32(env.wallet_aliases["cat"])
    )
    assert current_derivation_index is not None
    await cat_wallet.get_cat_puzzle_hash(new=True)
    next_derivation_index = await env.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
        uint32(env.wallet_aliases["cat"])
    )
    assert next_derivation_index is not None
    assert current_derivation_index.index < next_derivation_index.index

    # Test a weird edge case where a new puzzle hash needs to get generated
    # First, we reset the used status of all puzzle hashes by re-adding them
    for puzhash in await env.wallet_state_manager.puzzle_store.get_all_puzzle_hashes():
        dr = await env.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(puzhash)
        assert dr is not None
        await env.wallet_state_manager.puzzle_store.add_derivation_paths([dr])

    # Then we make sure that even though we asked for a used puzzle hash, it still gives us an unused one
    unused_count = await env.wallet_state_manager.puzzle_store.get_used_count(uint32(env.wallet_aliases["cat"]))
    await cat_wallet.get_cat_puzzle_hash(new=False)
    assert unused_count < await env.wallet_state_manager.puzzle_store.get_used_count(uint32(env.wallet_aliases["cat"]))
