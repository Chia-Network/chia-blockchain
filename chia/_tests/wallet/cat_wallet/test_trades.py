from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Tuple, Union

import pytest
from chia_rs import G2Element

from chia._tests.conftest import SOFTFORK_HEIGHTS
from chia._tests.environments.wallet import WalletStateTransition, WalletTestFramework
from chia._tests.util.time_out_assert import time_out_assert
from chia._tests.wallet.vc_wallet.test_vc_wallet import mint_cr_cat
from chia.consensus.cost_calculator import NPCResult
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.conditions import CreateCoinAnnouncement, parse_conditions_non_consensus
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trade_manager import TradeManager
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.vc_wallet.cr_cat_drivers import ProofsChecker
from chia.wallet.vc_wallet.cr_cat_wallet import CRCATWallet
from chia.wallet.vc_wallet.vc_store import VCProofs
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

OfferSummary = Dict[Union[int, bytes32], int]


async def get_trade_and_status(trade_manager: TradeManager, trade: TradeRecord) -> TradeStatus:
    trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
    if trade_rec is not None:
        return TradeStatus(trade_rec.status)
    raise ValueError("Couldn't find the trade record")


# This deliberate parameterization may at first look like we're neglecting quite a few cases.
# However, active_softfork_height is only used is the case where we test aggregation.
# We do not test aggregation in a number of cases because it's not correlated with a lot of these parameters.
# So to avoid the overhead of start up for identical tests, we only change the softfork param for the tests that use it.
# To pin down the behavior that we intend to eventually deprecate, it only gets one test case.
@pytest.mark.anyio
@pytest.mark.parametrize(
    "wallet_environments,credential_restricted,active_softfork_height",
    [
        (
            {"num_environments": 2, "trusted": True, "blocks_needed": [1, 1], "reuse_puzhash": True},
            True,
            SOFTFORK_HEIGHTS[0],
        ),
        (
            {"num_environments": 2, "trusted": True, "blocks_needed": [1, 1], "reuse_puzhash": True},
            False,
            SOFTFORK_HEIGHTS[0],
        ),
        (
            {"num_environments": 2, "trusted": True, "blocks_needed": [1, 1], "reuse_puzhash": False},
            True,
            SOFTFORK_HEIGHTS[0],
        ),
        (
            {"num_environments": 2, "trusted": False, "blocks_needed": [1, 1], "reuse_puzhash": True},
            True,
            SOFTFORK_HEIGHTS[0],
        ),
        (
            {"num_environments": 2, "trusted": False, "blocks_needed": [1, 1], "reuse_puzhash": False},
            False,
            SOFTFORK_HEIGHTS[0],
        ),
        (
            {"num_environments": 2, "trusted": False, "blocks_needed": [1, 1], "reuse_puzhash": True},
            False,
            SOFTFORK_HEIGHTS[0],
        ),
        (
            {"num_environments": 2, "trusted": False, "blocks_needed": [1, 1], "reuse_puzhash": False},
            True,
            SOFTFORK_HEIGHTS[0],
        ),
        *(
            ({"num_environments": 2, "trusted": True, "blocks_needed": [1, 1], "reuse_puzhash": False}, False, height)
            for height in SOFTFORK_HEIGHTS
        ),
    ],
    indirect=["wallet_environments"],
)
async def test_cat_trades(
    wallet_environments: WalletTestFramework,
    credential_restricted: bool,
    active_softfork_height: uint32,
) -> None:
    # Setup
    env_maker = wallet_environments.environments[0]
    env_taker = wallet_environments.environments[1]
    wallet_node_maker = env_maker.node
    wallet_node_taker = env_taker.node
    client_maker = env_maker.rpc_client
    client_taker = env_taker.rpc_client
    wallet_maker = env_maker.xch_wallet
    wallet_taker = env_taker.xch_wallet
    full_node = wallet_environments.full_node

    trusted = len(wallet_node_maker.config["trusted_peers"]) > 0

    # Because making/taking CR-CATs is asymetrical, approving the hacked together aggregation test will fail
    # The taker is "making" offers that it is approving with a VC which multiple actual makers would never do
    # This is really a test of CATOuterPuzzle anyways and is not correlated with any of our params
    test_aggregation = not credential_restricted and not wallet_environments.tx_config.reuse_puzhash and trusted

    # Create two new CATs, one in each wallet
    if credential_restricted:
        # Aliasing
        env_maker.wallet_aliases = {
            "xch": 1,
            "did": 2,
            "cat": 3,
            "vc": 4,
            "new cat": 5,
        }
        env_taker.wallet_aliases = {
            "xch": 1,
            "did": 2,
            "new cat": 3,
            "vc": 4,
            "cat": 5,
        }

        # Mint some DIDs
        async with wallet_maker.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_maker.wallet_state_manager,
                wallet_maker,
                uint64(1),
                action_scope,
            )
        async with wallet_taker.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_taker.wallet_state_manager,
                wallet_taker,
                uint64(1),
                action_scope,
            )
        did_id_maker = bytes32.from_hexstr(did_wallet_maker.get_my_DID())
        did_id_taker = bytes32.from_hexstr(did_wallet_taker.get_my_DID())

        # Mint some CR-CATs
        tail_maker = Program.to([3, (1, "maker"), None, None])
        tail_taker = Program.to([3, (1, "taker"), None, None])
        proofs_checker_maker = ProofsChecker(["foo", "bar"])
        proofs_checker_taker = ProofsChecker(["bar", "zap"])
        authorized_providers: List[bytes32] = [did_id_maker, did_id_taker]
        cat_wallet_maker: CATWallet = await CRCATWallet.get_or_create_wallet_for_cat(
            wallet_node_maker.wallet_state_manager,
            wallet_maker,
            tail_maker.get_tree_hash().hex(),
            None,
            authorized_providers,
            proofs_checker_maker,
        )
        new_cat_wallet_taker: CATWallet = await CRCATWallet.get_or_create_wallet_for_cat(
            wallet_node_taker.wallet_state_manager,
            wallet_taker,
            tail_taker.get_tree_hash().hex(),
            None,
            authorized_providers,
            proofs_checker_taker,
        )
        await mint_cr_cat(
            1,
            wallet_maker,
            wallet_node_maker,
            client_maker,
            full_node,
            authorized_providers,
            tail_maker,
            proofs_checker_maker,
        )
        await mint_cr_cat(
            1,
            wallet_taker,
            wallet_node_taker,
            client_taker,
            full_node,
            authorized_providers,
            tail_taker,
            proofs_checker_taker,
        )

        await wallet_environments.process_pending_states(
            [
                # Balance checking for this scenario is covered in tests/wallet/vc_wallet/test_vc_lifecycle
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "did": {"init": True, "set_remainder": True},
                        "cat": {"init": True, "set_remainder": True},
                    },
                    post_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "did": {"set_remainder": True},
                        "cat": {"set_remainder": True},
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "did": {"init": True, "set_remainder": True},
                        "new cat": {"init": True, "set_remainder": True},
                    },
                    post_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "did": {"set_remainder": True},
                        "new cat": {"set_remainder": True},
                    },
                ),
            ]
        )

        # Mint some VCs that can spend the CR-CATs
        vc_record_maker = (
            await client_maker.vc_mint(
                did_id_maker, wallet_environments.tx_config, target_address=await wallet_maker.get_new_puzzlehash()
            )
        ).vc_record
        vc_record_taker = (
            await client_taker.vc_mint(
                did_id_taker, wallet_environments.tx_config, target_address=await wallet_taker.get_new_puzzlehash()
            )
        ).vc_record
        await wallet_environments.process_pending_states(
            [
                # Balance checking for this scenario is covered in tests/wallet/vc_wallet/test_vc_lifecycle
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "vc": {"init": True, "set_remainder": True},
                    },
                    post_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "vc": {"set_remainder": True},
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "vc": {"init": True, "set_remainder": True},
                    },
                    post_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "vc": {"set_remainder": True},
                    },
                ),
            ]
        )

        proofs_maker = VCProofs({"foo": "1", "bar": "1", "zap": "1"})
        proof_root_maker: bytes32 = proofs_maker.root()
        await client_maker.vc_spend(
            vc_record_maker.vc.launcher_id,
            wallet_environments.tx_config,
            new_proof_hash=proof_root_maker,
        )

        proofs_taker = VCProofs({"foo": "1", "bar": "1", "zap": "1"})
        proof_root_taker: bytes32 = proofs_taker.root()
        await client_taker.vc_spend(
            vc_record_taker.vc.launcher_id,
            wallet_environments.tx_config,
            new_proof_hash=proof_root_taker,
        )
        await wallet_environments.process_pending_states(
            [
                # Balance checking for this scenario is covered in tests/wallet/vc_wallet/test_vc_lifecycle
                WalletStateTransition(
                    pre_block_balance_updates={
                        "did": {"set_remainder": True},
                        "vc": {"set_remainder": True},
                    },
                    post_block_balance_updates={
                        "did": {"set_remainder": True},
                        "vc": {"set_remainder": True},
                    },
                ),
                WalletStateTransition(
                    pre_block_balance_updates={
                        "did": {"set_remainder": True},
                        "vc": {"set_remainder": True},
                    },
                    post_block_balance_updates={
                        "did": {"set_remainder": True},
                        "vc": {"set_remainder": True},
                    },
                ),
            ]
        )
    else:
        # Aliasing
        env_maker.wallet_aliases = {
            "xch": 1,
            "cat": 2,
            "new cat": 3,
        }
        env_taker.wallet_aliases = {
            "xch": 1,
            "new cat": 2,
            "cat": 3,
        }

        # Mint some standard CATs
        async with wallet_maker.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            cat_wallet_maker = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager,
                wallet_maker,
                {"identifier": "genesis_by_id"},
                uint64(100),
                action_scope,
            )

        async with wallet_taker.wallet_state_manager.new_action_scope(
            wallet_environments.tx_config, push=True
        ) as action_scope:
            new_cat_wallet_taker = await CATWallet.create_new_cat_wallet(
                wallet_node_taker.wallet_state_manager,
                wallet_taker,
                {"identifier": "genesis_by_id"},
                uint64(100),
                action_scope,
            )

        await wallet_environments.process_pending_states(
            [
                # Balance checking for this scenario is covered in test_cat_wallet
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
                WalletStateTransition(
                    pre_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "new cat": {"init": True, "set_remainder": True},
                    },
                    post_block_balance_updates={
                        "xch": {"set_remainder": True},
                        "new cat": {"set_remainder": True},
                    },
                ),
            ]
        )

    if credential_restricted:
        await client_maker.vc_add_proofs(proofs_maker.key_value_pairs)
        assert await client_maker.vc_get_proofs_for_root(proof_root_maker) == proofs_maker.key_value_pairs
        vc_records, fetched_proofs = await client_maker.vc_get_list()
        assert len(vc_records) == 1
        assert fetched_proofs[proof_root_maker.hex()] == proofs_maker.key_value_pairs

        await client_taker.vc_add_proofs(proofs_taker.key_value_pairs)
        assert await client_taker.vc_get_proofs_for_root(proof_root_taker) == proofs_taker.key_value_pairs
        vc_records, fetched_proofs = await client_taker.vc_get_list()
        assert len(vc_records) == 1
        assert fetched_proofs[proof_root_taker.hex()] == proofs_taker.key_value_pairs

    # Add the taker's CAT to the maker's wallet
    if credential_restricted:
        new_cat_wallet_maker: CATWallet = await CRCATWallet.get_or_create_wallet_for_cat(
            wallet_node_maker.wallet_state_manager,
            wallet_maker,
            new_cat_wallet_taker.get_asset_id(),
            None,
            authorized_providers,
            proofs_checker_taker,
        )
    else:
        new_cat_wallet_maker = await CATWallet.get_or_create_wallet_for_cat(
            wallet_node_maker.wallet_state_manager, wallet_maker, new_cat_wallet_taker.get_asset_id()
        )

    await env_maker.change_balances(
        {
            "new cat": {
                "init": True,
                "confirmed_wallet_balance": 0,
                "unconfirmed_wallet_balance": 0,
                "spendable_balance": 0,
                "pending_coin_removal_count": 0,
                "pending_change": 0,
                "max_send_amount": 0,
            }
        }
    )
    await env_maker.check_balances()

    # Create the trade parameters
    chia_for_cat: OfferSummary = {
        wallet_maker.id(): -1,
        bytes32.from_hexstr(new_cat_wallet_maker.get_asset_id()): 2,  # This is the CAT that the taker made
    }
    cat_for_chia: OfferSummary = {
        wallet_maker.id(): 3,
        cat_wallet_maker.id(): -4,  # The taker has no knowledge of this CAT yet
    }
    cat_for_cat: OfferSummary = {
        bytes32.from_hexstr(cat_wallet_maker.get_asset_id()): -5,
        new_cat_wallet_maker.id(): 6,
    }
    chia_for_multiple_cat: OfferSummary = {
        wallet_maker.id(): -7,
        cat_wallet_maker.id(): 8,
        new_cat_wallet_maker.id(): 9,
    }
    multiple_cat_for_chia: OfferSummary = {
        wallet_maker.id(): 10,
        cat_wallet_maker.id(): -11,
        new_cat_wallet_maker.id(): -12,
    }
    chia_and_cat_for_cat: OfferSummary = {
        wallet_maker.id(): -13,
        cat_wallet_maker.id(): -14,
        new_cat_wallet_maker.id(): 15,
    }

    driver_dict: Dict[bytes32, PuzzleInfo] = {}
    for wallet in (cat_wallet_maker, new_cat_wallet_maker):
        asset_id: str = wallet.get_asset_id()
        driver_item: Dict[str, Any] = {
            "type": AssetType.CAT.value,
            "tail": "0x" + asset_id,
        }
        if credential_restricted:
            driver_item["also"] = {
                "type": AssetType.CR.value,
                "authorized_providers": ["0x" + provider.hex() for provider in authorized_providers],
                "proofs_checker": (
                    proofs_checker_maker.as_program()
                    if wallet == cat_wallet_maker
                    else proofs_checker_taker.as_program()
                ),
            }
        driver_dict[bytes32.from_hexstr(asset_id)] = PuzzleInfo(driver_item)

    trade_manager_maker = env_maker.wallet_state_manager.trade_manager
    trade_manager_taker = env_taker.wallet_state_manager.trade_manager
    maker_unused_dr = await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
        uint32(1)
    )
    assert maker_unused_dr is not None
    maker_unused_index = maker_unused_dr.index
    taker_unused_dr = await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
        uint32(1)
    )
    assert taker_unused_dr is not None
    taker_unused_index = taker_unused_dr.index
    # Execute all of the trades
    # chia_for_cat
    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            chia_for_cat, action_scope, fee=uint64(1)
        )
    assert error is None
    assert success is True
    assert trade_make is not None

    peer = wallet_node_taker.get_full_node_peer()
    [maker_offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            maker_offer,
            peer,
            action_scope,
            fee=uint64(1),
        )

    if test_aggregation:
        first_offer = Offer.from_bytes(trade_take.offer)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -2,
                        "<=#max_send_amount": -2,
                        # Unconfirmed balance doesn't change because offer may not complete
                        "unconfirmed_wallet_balance": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "pending_coin_removal_count": -1,
                        "confirmed_wallet_balance": -2,  # One for offered XCH, one for fee
                        "unconfirmed_wallet_balance": -2,  # One for offered XCH, one for fee
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                    },
                    "new cat": (
                        {
                            # No change if credential_restricted because pending approval balance needs to be claimed
                            "confirmed_wallet_balance": 0,
                            "unconfirmed_wallet_balance": 0,
                            "spendable_balance": 0,
                            "max_send_amount": 0,
                            "pending_change": 0,
                            "unspent_coin_count": 0,
                        }
                        if credential_restricted
                        else {
                            "confirmed_wallet_balance": 2,
                            "unconfirmed_wallet_balance": 2,
                            "spendable_balance": 2,
                            "max_send_amount": 2,
                            "unspent_coin_count": 1,
                        }
                    ),
                },
                post_block_additional_balance_info=(
                    {
                        "new cat": {
                            "pending_approval_balance": 2,
                        }
                    }
                    if credential_restricted
                    else {}
                ),
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -2,
                        "<=#max_send_amount": -2,
                        # Unconfirmed balance doesn't change because receiveing 1 XCH and spending 1 in fee
                        "unconfirmed_wallet_balance": 0,
                        ">=#pending_change": 1,  # any amount increase
                    },
                    "new cat": {
                        "unconfirmed_wallet_balance": -2,
                        "pending_coin_removal_count": 1,
                        "pending_change": 98,
                        "<=#spendable_balance": -2,
                        "<=#max_send_amount": -2,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": 1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
                post_block_balance_updates={
                    "xch": {
                        "pending_coin_removal_count": -1,
                        "unspent_coin_count": 1,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        # Confirmed balance doesn't change because receiveing 1 XCH and spending 1 in fee
                        "confirmed_wallet_balance": 0,
                        "<=#pending_change": 1,  # any amount decrease
                    },
                    "new cat": {
                        "confirmed_wallet_balance": -2,
                        "pending_coin_removal_count": -1,
                        "pending_change": -98,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": -1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
            ),
        ]
    )

    if credential_restricted:
        await client_maker.crcat_approve_pending(
            new_cat_wallet_maker.id(),
            uint64(2),
            DEFAULT_TX_CONFIG,
        )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "new cat": {
                            "unconfirmed_wallet_balance": 2,
                            "pending_coin_removal_count": 1,
                            "pending_change": 2,  # This is a little weird but fits the current definition
                        },
                        "vc": {
                            "pending_coin_removal_count": 1,
                        },
                    },
                    pre_block_additional_balance_info={
                        "new cat": {
                            "pending_approval_balance": 2,
                        }
                    },
                    post_block_balance_updates={
                        "new cat": {
                            "confirmed_wallet_balance": 2,
                            "spendable_balance": 2,
                            "max_send_amount": 2,
                            "pending_change": -2,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": -1,
                        },
                        "vc": {
                            "pending_coin_removal_count": -1,
                        },
                    },
                    post_block_additional_balance_info={
                        "new cat": {
                            "pending_approval_balance": 0,
                        }
                    },
                ),
                WalletStateTransition(),
            ]
        )

    if wallet_environments.tx_config.reuse_puzhash:
        # Check if unused index changed
        maker_unused_dr = await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
            uint32(1)
        )
        assert maker_unused_dr is not None
        assert maker_unused_index == maker_unused_dr.index
        taker_unused_dr = await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
            uint32(1)
        )
        assert taker_unused_dr is not None
        assert taker_unused_index == taker_unused_dr.index
    else:
        maker_unused_dr = await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
            uint32(1)
        )
        assert maker_unused_dr is not None
        assert maker_unused_index < maker_unused_dr.index
        taker_unused_dr = await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
            uint32(1)
        )
        assert taker_unused_dr is not None
        assert taker_unused_index < taker_unused_dr.index

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    async def assert_trade_tx_number(wallet_node: WalletNode, trade_id: bytes32, number: int) -> bool:
        txs = await wallet_node.wallet_state_manager.tx_store.get_transactions_by_trade_id(trade_id)
        return len(txs) == number

    await time_out_assert(15, assert_trade_tx_number, True, wallet_node_maker, trade_make.trade_id, 1)
    # CR-CATs will also have a TX record for the VC
    await time_out_assert(
        15, assert_trade_tx_number, True, wallet_node_taker, trade_take.trade_id, 4 if credential_restricted else 3
    )

    # cat_for_chia
    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_chia, action_scope)
    assert error is None
    assert success is True
    assert trade_make is not None

    [maker_offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer),
            peer,
            action_scope,
            fee=uint64(1),
        )

    # Testing a precious display bug real quick
    xch_tx: TransactionRecord = next(tx for tx in action_scope.side_effects.transactions if tx.wallet_id == 1)
    assert xch_tx.amount == 3
    assert xch_tx.fee_amount == 1

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -4,
                        "<=#max_send_amount": -4,
                        # Unconfirmed balance doesn't change because offer may not complete
                        "unconfirmed_wallet_balance": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 3,
                        "unconfirmed_wallet_balance": 3,
                        "spendable_balance": 3,
                        "max_send_amount": 3,
                        "unspent_coin_count": 1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": -4,
                        "unconfirmed_wallet_balance": -4,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -4,  # -3 for offer, -1 for fee
                        "<=#spendable_balance": -4,
                        "<=#max_send_amount": -4,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                    },
                    "cat": {
                        "init": True,
                        "confirmed_wallet_balance": 0,
                        "unconfirmed_wallet_balance": 4,
                        "spendable_balance": 0,
                        "pending_change": 0,
                        "max_send_amount": 0,
                        "unspent_coin_count": 0,
                        "pending_coin_removal_count": 0,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": 1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -4,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": 1,  # any amount decrease
                    },
                    "cat": {
                        "unspent_coin_count": 1,
                        "spendable_balance": 4,
                        "max_send_amount": 4,
                        "confirmed_wallet_balance": 4,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": -1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
            ),
        ]
    )

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    await time_out_assert(15, assert_trade_tx_number, True, wallet_node_maker, trade_make.trade_id, 1)
    await time_out_assert(
        15, assert_trade_tx_number, True, wallet_node_taker, trade_take.trade_id, 3 if credential_restricted else 2
    )

    # cat_for_cat
    maker_unused_dr = await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
        uint32(1)
    )
    assert maker_unused_dr is not None
    maker_unused_index = maker_unused_dr.index
    taker_unused_dr = await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
        uint32(1)
    )
    assert taker_unused_dr is not None
    taker_unused_index = taker_unused_dr.index
    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_cat, action_scope)
    assert error is None
    assert success is True
    assert trade_make is not None
    [maker_offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer),
            peer,
            action_scope,
        )

    if test_aggregation:
        second_offer = Offer.from_bytes(trade_take.offer)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -5,
                        "<=#max_send_amount": -5,
                        # Unconfirmed balance doesn't change because offer may not complete
                        "unconfirmed_wallet_balance": 0,
                    },
                },
                post_block_balance_updates={
                    "new cat": (
                        {
                            # No change if credential_restricted because pending approval balance needs to be claimed
                            "confirmed_wallet_balance": 0,
                            "unconfirmed_wallet_balance": 0,
                            "spendable_balance": 0,
                            "max_send_amount": 0,
                            "unspent_coin_count": 0,
                        }
                        if credential_restricted
                        else {
                            "confirmed_wallet_balance": 6,
                            "unconfirmed_wallet_balance": 6,
                            "spendable_balance": 6,
                            "max_send_amount": 6,
                            "unspent_coin_count": 1,
                        }
                    ),
                    "cat": {
                        "confirmed_wallet_balance": -5,
                        "unconfirmed_wallet_balance": -5,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "pending_coin_removal_count": -1,
                    },
                },
                post_block_additional_balance_info=(
                    {
                        "new cat": {
                            "pending_approval_balance": 6,
                        }
                    }
                    if credential_restricted
                    else {}
                ),
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "unconfirmed_wallet_balance": 5,
                    },
                    "new cat": {
                        "unconfirmed_wallet_balance": -6,
                        "pending_change": 92,
                        "<=#spendable_balance": -6,
                        "<=#max_send_amount": -6,
                        "pending_coin_removal_count": 1,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": 1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
                post_block_balance_updates={
                    "cat": {
                        "unspent_coin_count": 1,
                        "spendable_balance": 5,
                        "max_send_amount": 5,
                        "confirmed_wallet_balance": 5,
                    },
                    "new cat": {
                        "confirmed_wallet_balance": -6,
                        "pending_change": -92,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "pending_coin_removal_count": -1,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": -1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
            ),
        ]
    )

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    if credential_restricted:
        await client_maker.crcat_approve_pending(
            new_cat_wallet_maker.id(),
            uint64(6),
            DEFAULT_TX_CONFIG,
        )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "new cat": {
                            "unconfirmed_wallet_balance": 6,
                            "pending_coin_removal_count": 1,
                            "pending_change": 6,  # This is a little weird but fits the current definition
                        },
                        "vc": {
                            "pending_coin_removal_count": 1,
                        },
                    },
                    pre_block_additional_balance_info={
                        "new cat": {
                            "pending_approval_balance": 6,
                        }
                    },
                    post_block_balance_updates={
                        "new cat": {
                            "confirmed_wallet_balance": 6,
                            "spendable_balance": 6,
                            "max_send_amount": 6,
                            "pending_change": -6,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": -1,
                        },
                        "vc": {
                            "pending_coin_removal_count": -1,
                        },
                    },
                    post_block_additional_balance_info={
                        "new cat": {
                            "pending_approval_balance": 0,
                        }
                    },
                ),
                WalletStateTransition(),
            ]
        )

    if wallet_environments.tx_config.reuse_puzhash:
        # Check if unused index changed
        maker_unused_dr = await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
            uint32(1)
        )
        assert maker_unused_dr is not None
        assert maker_unused_index == maker_unused_dr.index
        taker_unused_dr = await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
            uint32(1)
        )
        assert taker_unused_dr is not None
        assert taker_unused_index == taker_unused_dr.index
    else:
        maker_unused_dr = await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
            uint32(1)
        )
        assert maker_unused_dr is not None
        assert maker_unused_index < maker_unused_dr.index
        taker_unused_dr = await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
            uint32(1)
        )
        assert taker_unused_dr is not None
        assert taker_unused_index < taker_unused_dr.index

    # chia_for_multiple_cat
    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            chia_for_multiple_cat,
            action_scope,
            driver_dict=driver_dict,
        )
    assert error is None
    assert success is True
    assert trade_make is not None

    [maker_offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer),
            peer,
            action_scope,
        )

    if test_aggregation:
        third_offer = Offer.from_bytes(trade_take.offer)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -7,
                        "<=#max_send_amount": -7,
                        # Unconfirmed balance doesn't change because offer may not complete
                        "unconfirmed_wallet_balance": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "pending_coin_removal_count": -1,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "unconfirmed_wallet_balance": -7,
                        "confirmed_wallet_balance": -7,
                    },
                    "cat": (
                        {
                            # No change if credential_restricted because pending approval balance needs to be claimed
                            "confirmed_wallet_balance": 0,
                            "unconfirmed_wallet_balance": 0,
                            "spendable_balance": 0,
                            "max_send_amount": 0,
                            "unspent_coin_count": 0,
                        }
                        if credential_restricted
                        else {
                            "confirmed_wallet_balance": 8,
                            "unconfirmed_wallet_balance": 8,
                            "spendable_balance": 8,
                            "max_send_amount": 8,
                            "unspent_coin_count": 1,
                        }
                    ),
                    "new cat": (
                        {
                            # No change if credential_restricted because pending approval balance needs to be claimed
                            "confirmed_wallet_balance": 0,
                            "unconfirmed_wallet_balance": 0,
                            "spendable_balance": 0,
                            "max_send_amount": 0,
                            "unspent_coin_count": 0,
                        }
                        if credential_restricted
                        else {
                            "confirmed_wallet_balance": 9,
                            "unconfirmed_wallet_balance": 9,
                            "spendable_balance": 9,
                            "max_send_amount": 9,
                            "unspent_coin_count": 1,
                        }
                    ),
                },
                post_block_additional_balance_info=(
                    {
                        "cat": {
                            "pending_approval_balance": 8,
                        },
                        "new cat": {
                            "pending_approval_balance": 9,
                        },
                    }
                    if credential_restricted
                    else {}
                ),
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": 7,
                    },
                    "cat": {
                        "unconfirmed_wallet_balance": -8,
                        "pending_change": 1,
                        "<=#spendable_balance": -8,
                        "<=#max_send_amount": -8,
                        "pending_coin_removal_count": 2,  # For the first time, we're using two coins in an offer
                    },
                    "new cat": {
                        "unconfirmed_wallet_balance": -9,
                        "pending_change": 83,
                        "<=#spendable_balance": -9,
                        "<=#max_send_amount": -9,
                        "pending_coin_removal_count": 1,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": 1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 7,
                        "spendable_balance": 7,
                        "max_send_amount": 7,
                        "unspent_coin_count": 1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": -8,
                        "pending_change": -1,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "pending_coin_removal_count": -2,
                        "unspent_coin_count": -1,
                    },
                    "new cat": {
                        "confirmed_wallet_balance": -9,
                        "pending_change": -83,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "pending_coin_removal_count": -1,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": -1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
            ),
        ]
    )

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    if credential_restricted:
        await client_maker.crcat_approve_pending(
            cat_wallet_maker.id(),
            uint64(8),
            DEFAULT_TX_CONFIG,
        )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "cat": {
                            "unconfirmed_wallet_balance": 8,
                            "pending_coin_removal_count": 1,
                            "pending_change": 8,  # This is a little weird but fits the current definition
                        },
                        "vc": {
                            "pending_coin_removal_count": 1,
                        },
                    },
                    pre_block_additional_balance_info={
                        "cat": {
                            "pending_approval_balance": 8,
                        },
                    },
                    post_block_balance_updates={
                        "cat": {
                            "confirmed_wallet_balance": 8,
                            "spendable_balance": 8,
                            "max_send_amount": 8,
                            "pending_change": -8,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": -1,
                        },
                        "vc": {
                            "pending_coin_removal_count": -1,
                        },
                    },
                    post_block_additional_balance_info={
                        "cat": {
                            "pending_approval_balance": 0,
                        },
                    },
                ),
                WalletStateTransition(),
            ]
        )

        await client_maker.crcat_approve_pending(
            new_cat_wallet_maker.id(),
            uint64(9),
            DEFAULT_TX_CONFIG,
        )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "new cat": {
                            "unconfirmed_wallet_balance": 9,
                            "pending_coin_removal_count": 1,
                            "pending_change": 9,  # This is a little weird but fits the current definition
                        },
                        "vc": {
                            "pending_coin_removal_count": 1,
                        },
                    },
                    pre_block_additional_balance_info={
                        "new cat": {
                            "pending_approval_balance": 9,
                        }
                    },
                    post_block_balance_updates={
                        "new cat": {
                            "confirmed_wallet_balance": 9,
                            "spendable_balance": 9,
                            "max_send_amount": 9,
                            "pending_change": -9,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": -1,
                        },
                        "vc": {
                            "pending_coin_removal_count": -1,
                        },
                    },
                    post_block_additional_balance_info={
                        "new cat": {
                            "pending_approval_balance": 0,
                        }
                    },
                ),
                WalletStateTransition(),
            ]
        )

    # multiple_cat_for_chia
    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            multiple_cat_for_chia,
            action_scope,
        )
    assert error is None
    assert success is True
    assert trade_make is not None
    [maker_offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer),
            peer,
            action_scope,
        )

    if test_aggregation:
        fourth_offer = Offer.from_bytes(trade_take.offer)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "cat": {
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -11,
                        "<=#max_send_amount": -11,
                        # Unconfirmed balance doesn't change because offer may not complete
                        "unconfirmed_wallet_balance": 0,
                    },
                    "new cat": {
                        "pending_coin_removal_count": 2,
                        "<=#spendable_balance": -12,
                        "<=#max_send_amount": -12,
                        # Unconfirmed balance doesn't change because offer may not complete
                        "unconfirmed_wallet_balance": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 10,
                        "unconfirmed_wallet_balance": 10,
                        "spendable_balance": 10,
                        "max_send_amount": 10,
                        "unspent_coin_count": 1,
                    },
                    "cat": {
                        "pending_coin_removal_count": -1,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "unconfirmed_wallet_balance": -11,
                        "confirmed_wallet_balance": -11,
                    },
                    "new cat": {
                        "pending_coin_removal_count": -2,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "unconfirmed_wallet_balance": -12,
                        "confirmed_wallet_balance": -12,
                        "unspent_coin_count": -1,
                    },
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": -10,
                        "<=#spendable_balance": -10,
                        "<=#max_send_amount": -10,
                        "pending_coin_removal_count": 1,
                        ">=#pending_change": 1,  # any amount increase
                    },
                    "cat": {
                        "unconfirmed_wallet_balance": 11,
                    },
                    "new cat": {
                        "unconfirmed_wallet_balance": 12,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": 1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -10,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "pending_coin_removal_count": -1,
                        "<=#pending_change": 1,  # any amount increase
                    },
                    "cat": {
                        "confirmed_wallet_balance": 11,
                        "spendable_balance": 11,
                        "max_send_amount": 11,
                        "unspent_coin_count": 1,
                    },
                    "new cat": {
                        "confirmed_wallet_balance": 12,
                        "spendable_balance": 12,
                        "max_send_amount": 12,
                        "unspent_coin_count": 1,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": -1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
            ),
        ]
    )

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    # chia_and_cat_for_cat
    async with trade_manager_maker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=False
    ) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            chia_and_cat_for_cat,
            action_scope,
        )
    assert error is None
    assert success is True
    assert trade_make is not None

    [maker_offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        wallet_environments.tx_config, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        trade_take = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer),
            peer,
            action_scope,
        )

    if test_aggregation:
        fifth_offer = Offer.from_bytes(trade_take.offer)

    await wallet_environments.process_pending_states(
        [
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "pending_coin_removal_count": 2,
                        "<=#spendable_balance": -13,
                        "<=#max_send_amount": -13,
                        # Unconfirmed balance doesn't change because offer may not complete
                        "unconfirmed_wallet_balance": 0,
                    },
                    "cat": {
                        "pending_coin_removal_count": 1,
                        "<=#spendable_balance": -14,
                        "<=#max_send_amount": -14,
                        # Unconfirmed balance doesn't change because offer may not complete
                        "unconfirmed_wallet_balance": 0,
                    },
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": -13,
                        "unconfirmed_wallet_balance": -13,
                        ">=#spendable_balance": 0,
                        ">=#max_send_amount": 0,
                        "unspent_coin_count": -2,
                        "pending_coin_removal_count": -2,
                    },
                    "cat": {
                        "pending_coin_removal_count": -1,
                        ">=#spendable_balance": 0,
                        ">=#max_send_amount": 0,
                        "unconfirmed_wallet_balance": -14,
                        "confirmed_wallet_balance": -14,
                    },
                    "new cat": (
                        {
                            "spendable_balance": 0,
                            "max_send_amount": 0,
                            "unconfirmed_wallet_balance": 0,
                            "confirmed_wallet_balance": 0,
                            "unspent_coin_count": 0,
                        }
                        if credential_restricted
                        else {
                            "spendable_balance": 15,
                            "max_send_amount": 15,
                            "unconfirmed_wallet_balance": 15,
                            "confirmed_wallet_balance": 15,
                            "unspent_coin_count": 1,
                        }
                    ),
                },
            ),
            WalletStateTransition(
                pre_block_balance_updates={
                    "xch": {
                        "unconfirmed_wallet_balance": 13,
                    },
                    "cat": {
                        "unconfirmed_wallet_balance": 14,
                    },
                    "new cat": {
                        "unconfirmed_wallet_balance": -15,
                        "pending_change": 68,
                        "<=#spendable_balance": -15,
                        "<=#max_send_amount": -15,
                        "pending_coin_removal_count": 1,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": 1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
                post_block_balance_updates={
                    "xch": {
                        "confirmed_wallet_balance": 13,
                        "spendable_balance": 13,
                        "max_send_amount": 13,
                        "unspent_coin_count": 1,
                    },
                    "cat": {
                        "confirmed_wallet_balance": 14,
                        "spendable_balance": 14,
                        "max_send_amount": 14,
                        "unspent_coin_count": 1,
                    },
                    "new cat": {
                        "confirmed_wallet_balance": -15,
                        "pending_change": -68,
                        ">#spendable_balance": 0,
                        ">#max_send_amount": 0,
                        "pending_coin_removal_count": -1,
                    },
                    **(
                        {
                            "vc": {
                                "pending_coin_removal_count": -1,
                            }
                        }
                        if credential_restricted
                        else {}
                    ),
                },
            ),
        ]
    )

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    if credential_restricted:
        await client_maker.crcat_approve_pending(
            new_cat_wallet_maker.id(),
            uint64(15),
            DEFAULT_TX_CONFIG,
        )

        await wallet_environments.process_pending_states(
            [
                WalletStateTransition(
                    pre_block_balance_updates={
                        "new cat": {
                            "unconfirmed_wallet_balance": 15,
                            "pending_coin_removal_count": 1,
                            "pending_change": 15,  # This is a little weird but fits the current definition
                        },
                        "vc": {
                            "pending_coin_removal_count": 1,
                        },
                    },
                    pre_block_additional_balance_info={
                        "new cat": {
                            "pending_approval_balance": 15,
                        }
                    },
                    post_block_balance_updates={
                        "new cat": {
                            "confirmed_wallet_balance": 15,
                            "spendable_balance": 15,
                            "max_send_amount": 15,
                            "pending_change": -15,
                            "unspent_coin_count": 1,
                            "pending_coin_removal_count": -1,
                        },
                        "vc": {
                            "pending_coin_removal_count": -1,
                        },
                    },
                    post_block_additional_balance_info={
                        "new cat": {
                            "pending_approval_balance": 0,
                        }
                    },
                ),
                WalletStateTransition(),
            ]
        )

    if test_aggregation:
        # This tests an edge case where aggregated offers the include > 2 of the same kind of CAT
        # (and therefore are solved as a complete ring)
        bundle = Offer.aggregate([first_offer, second_offer, third_offer, fourth_offer, fifth_offer]).to_valid_spend()
        program = simple_solution_generator(bundle)
        result: NPCResult = get_name_puzzle_conditions(
            program, INFINITE_COST, mempool_mode=True, height=active_softfork_height, constants=DEFAULT_CONSTANTS
        )
        assert result.error is None


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.anyio
async def test_trade_cancellation(
    wallets_prefarm: Tuple[Tuple[WalletNode, int], Tuple[WalletNode, int], FullNodeSimulator]
) -> None:
    (wallet_node_maker, maker_funds), (wallet_node_taker, taker_funds), full_node = wallets_prefarm
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    xch_to_cat_amount = uint64(100)

    async with wallet_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            wallet_node_maker.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            xch_to_cat_amount,
            action_scope,
        )

    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
    maker_funds -= xch_to_cat_amount
    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

    cat_for_chia: OfferSummary = {
        wallet_maker.id(): 1,
        cat_wallet_maker.id(): -2,
    }

    chia_for_cat: OfferSummary = {
        wallet_maker.id(): -3,
        cat_wallet_maker.id(): 4,
    }

    trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_chia, action_scope)
    assert error is None
    assert success is True
    assert trade_make is not None

    # Cancelling the trade and trying an ID that doesn't exist just in case
    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        await trade_manager_maker.cancel_pending_offers(
            [trade_make.trade_id, bytes32([0] * 32)], action_scope, secure=False
        )
    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    # Due to current mempool rules, trying to force a take out of the mempool with a cancel will not work.
    # Uncomment this when/if it does

    # [maker_offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers(
    #   [Offer.from_bytes(trade_make.offer)]
    # )
    # trade_take = await trade_manager_taker.respond_to_offer(
    #     maker_offer,
    # )
    # tx_records = await wallet_taker.wallet_state_manager.add_pending_transactions(
    #   action_scope.side_effects.transactions,
    #   additional_signing_responses=signing_response,
    # )
    # await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
    # assert trade_take is not None
    # assert tx_records is not None
    # await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CONFIRM, trade_manager_taker, trade_take)
    # await time_out_assert(
    #     15,
    #     full_node.tx_id_in_mempool,
    #     True,
    #     Offer.from_bytes(trade_take.offer).to_valid_spend().name(),
    # )

    fee = uint64(2_000_000_000_000)

    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await trade_manager_maker.cancel_pending_offers([trade_make.trade_id], action_scope, fee=fee, secure=True)
    await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    sum_of_outgoing = uint64(0)
    sum_of_incoming = uint64(0)
    for tx in action_scope.side_effects.transactions:
        if tx.type == TransactionType.OUTGOING_TX.value:
            sum_of_outgoing = uint64(sum_of_outgoing + tx.amount)
        elif tx.type == TransactionType.INCOMING_TX.value:
            sum_of_incoming = uint64(sum_of_incoming + tx.amount)
    assert (sum_of_outgoing - sum_of_incoming) == 0

    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)
    # await time_out_assert(15, get_trade_and_status, TradeStatus.FAILED, trade_manager_taker, trade_take)

    await time_out_assert(15, wallet_maker.get_pending_change_balance, 0)
    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds - fee)
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
    await time_out_assert(15, wallet_taker.get_confirmed_balance, taker_funds)

    peer = wallet_node_taker.get_full_node_peer()
    with pytest.raises(ValueError, match="This offer is no longer valid"):
        async with trade_manager_taker.wallet_state_manager.new_action_scope(
            DEFAULT_TX_CONFIG, push=False
        ) as action_scope:
            await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer, action_scope)

    # Now we're going to create the other way around for test coverage sake
    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat, action_scope)
    assert error is None
    assert success is True
    assert trade_make is not None

    # This take should fail since we have no CATs to fulfill it with
    with pytest.raises(
        ValueError,
        match=f"Do not have a wallet for asset ID: {cat_wallet_maker.get_asset_id()} to fulfill offer",
    ):
        async with trade_manager_taker.wallet_state_manager.new_action_scope(
            DEFAULT_TX_CONFIG, push=False
        ) as action_scope:
            await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer, action_scope)

    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await trade_manager_maker.cancel_pending_offers([trade_make.trade_id], action_scope, fee=uint64(0), secure=True)
    await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    # Now let's test the case where two coins need to be spent in order to cancel
    chia_and_cat_for_something: OfferSummary = {
        wallet_maker.id(): -5,
        cat_wallet_maker.id(): -6,
        bytes32([0] * 32): 1,  # Doesn't matter
    }

    # Now we're going to create the other way around for test coverage sake
    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            chia_and_cat_for_something,
            action_scope,
            driver_dict={bytes32([0] * 32): PuzzleInfo({"type": AssetType.CAT.value, "tail": "0x" + bytes(32).hex()})},
        )
    assert error is None
    assert success is True
    assert trade_make is not None

    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await trade_manager_maker.cancel_pending_offers([trade_make.trade_id], action_scope, fee=uint64(0), secure=True)

    # Check an announcement ring has been created
    total_spend = SpendBundle.aggregate(
        [tx.spend_bundle for tx in action_scope.side_effects.transactions if tx.spend_bundle is not None]
    )
    all_conditions: List[Program] = []
    creations: List[CreateCoinAnnouncement] = []
    announcement_nonce = std_hash(trade_make.trade_id)
    for spend in total_spend.coin_spends:
        all_conditions.extend(
            [
                c.to_program()
                for c in parse_conditions_non_consensus(
                    spend.puzzle_reveal.to_program().run(spend.solution.to_program()).as_iter(), abstractions=False
                )
            ]
        )
        creations.append(CreateCoinAnnouncement(msg=announcement_nonce, coin_id=spend.coin.name()))
    for creation in creations:
        assert creation.corresponding_assertion().to_program() in all_conditions

    await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.anyio
async def test_trade_cancellation_balance_check(
    wallets_prefarm: Tuple[Tuple[WalletNode, int], Tuple[WalletNode, int], FullNodeSimulator]
) -> None:
    (wallet_node_maker, maker_funds), _, full_node = wallets_prefarm
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet

    xch_to_cat_amount = uint64(100)

    async with wallet_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            wallet_node_maker.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            xch_to_cat_amount,
            action_scope,
        )

    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
    maker_funds -= xch_to_cat_amount
    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

    chia_for_cat: OfferSummary = {
        wallet_maker.id(): -(await wallet_maker.get_spendable_balance()),
        cat_wallet_maker.id(): 4,
    }

    trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager

    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat, action_scope)
    await time_out_assert(10, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make)
    assert error is None
    assert success is True
    assert trade_make is not None
    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await trade_manager_maker.cancel_pending_offers([trade_make.trade_id], action_scope, fee=uint64(0), secure=True)
    await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.anyio
async def test_trade_conflict(
    three_wallets_prefarm: Tuple[
        Tuple[WalletNode, int], Tuple[WalletNode, int], Tuple[WalletNode, int], FullNodeSimulator
    ]
) -> None:
    ((wallet_node_maker, maker_funds), (wallet_node_taker, _), (wallet_node_trader, _), full_node) = (
        three_wallets_prefarm
    )
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    xch_to_cat_amount = uint64(100)

    async with wallet_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            wallet_node_maker.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            xch_to_cat_amount,
            action_scope,
        )

    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
    maker_funds -= xch_to_cat_amount
    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

    chia_for_cat: OfferSummary = {
        wallet_maker.id(): 1000,
        cat_wallet_maker.id(): -4,
    }

    trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager
    trade_manager_trader = wallet_node_trader.wallet_state_manager.trade_manager

    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat, action_scope)
    await time_out_assert(10, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make)
    assert error is None
    assert success is True
    assert trade_make is not None
    peer = wallet_node_taker.get_full_node_peer()
    offer = Offer.from_bytes(trade_make.offer)
    [offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers([offer])
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        DEFAULT_TX_CONFIG, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        tr1 = await trade_manager_taker.respond_to_offer(offer, peer, action_scope, fee=uint64(10))
    await full_node.wait_transaction_records_entered_mempool(records=action_scope.side_effects.transactions)
    # we shouldn't be able to respond to a duplicate offer
    with pytest.raises(ValueError):
        async with trade_manager_taker.wallet_state_manager.new_action_scope(
            DEFAULT_TX_CONFIG, push=False
        ) as action_scope:
            await trade_manager_taker.respond_to_offer(offer, peer, action_scope, fee=uint64(10))
    await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CONFIRM, trade_manager_taker, tr1)
    # pushing into mempool while already in it should fail
    [offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers([offer])
    async with trade_manager_trader.wallet_state_manager.new_action_scope(
        DEFAULT_TX_CONFIG, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        tr2 = await trade_manager_trader.respond_to_offer(offer, peer, action_scope, fee=uint64(10))
    assert await trade_manager_trader.get_coins_of_interest()
    offer_tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()
    await full_node.process_transaction_records(records=offer_tx_records)
    await full_node.wait_for_wallet_synced(wallet_node=wallet_node_trader, timeout=20)
    await time_out_assert(15, get_trade_and_status, TradeStatus.FAILED, trade_manager_trader, tr2)


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.anyio
async def test_trade_bad_spend(
    wallets_prefarm: Tuple[Tuple[WalletNode, int], Tuple[WalletNode, int], FullNodeSimulator]
) -> None:
    (wallet_node_maker, maker_funds), (wallet_node_taker, _), full_node = wallets_prefarm
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    xch_to_cat_amount = uint64(100)

    async with wallet_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            wallet_node_maker.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            xch_to_cat_amount,
            action_scope,
        )

    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
    maker_funds -= xch_to_cat_amount
    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

    chia_for_cat: OfferSummary = {
        wallet_maker.id(): 1000,
        cat_wallet_maker.id(): -4,
    }

    trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat, action_scope)
    await time_out_assert(30, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make)
    assert error is None
    assert success is True
    assert trade_make is not None
    peer = wallet_node_taker.get_full_node_peer()
    offer = Offer.from_bytes(trade_make.offer)
    bundle = WalletSpendBundle(coin_spends=offer._bundle.coin_spends, aggregated_signature=G2Element())
    offer = dataclasses.replace(offer, _bundle=bundle)
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        DEFAULT_TX_CONFIG, push=True, sign=False
    ) as action_scope:
        tr1 = await trade_manager_taker.respond_to_offer(offer, peer, action_scope, fee=uint64(10))
    wallet_node_taker.wallet_tx_resend_timeout_secs = 0  # don't wait for resend

    def check_wallet_cache_empty() -> bool:
        return wallet_node_taker._tx_messages_in_progress == {}

    for _ in range(10):
        await wallet_node_taker._resend_queue()
        await time_out_assert(5, check_wallet_cache_empty, True)
    offer_tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()
    await full_node.process_transaction_records(records=offer_tx_records)
    await time_out_assert(30, get_trade_and_status, TradeStatus.FAILED, trade_manager_taker, tr1)


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.anyio
async def test_trade_high_fee(
    wallets_prefarm: Tuple[Tuple[WalletNode, int], Tuple[WalletNode, int], FullNodeSimulator]
) -> None:
    (wallet_node_maker, maker_funds), (wallet_node_taker, _), full_node = wallets_prefarm
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    xch_to_cat_amount = uint64(100)

    async with wallet_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            wallet_node_maker.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            xch_to_cat_amount,
            action_scope,
        )

    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
    maker_funds -= xch_to_cat_amount
    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

    chia_for_cat: OfferSummary = {
        wallet_maker.id(): 1000,
        cat_wallet_maker.id(): -4,
    }

    trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat, action_scope)
    await time_out_assert(10, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make)
    assert error is None
    assert success is True
    assert trade_make is not None
    peer = wallet_node_taker.get_full_node_peer()
    [offer], signing_response = await wallet_node_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make.offer)]
    )
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        DEFAULT_TX_CONFIG, push=True, additional_signing_responses=signing_response
    ) as action_scope:
        tr1 = await trade_manager_taker.respond_to_offer(offer, peer, action_scope, fee=uint64(1000000000000))
    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, tr1)


@pytest.mark.parametrize("trusted", [True, False])
@pytest.mark.anyio
async def test_aggregated_trade_state(
    wallets_prefarm: Tuple[Tuple[WalletNode, int], Tuple[WalletNode, int], FullNodeSimulator]
) -> None:
    (wallet_node_maker, maker_funds), (wallet_node_taker, _), full_node = wallets_prefarm
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    xch_to_cat_amount = uint64(100)

    async with wallet_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        cat_wallet_maker = await CATWallet.create_new_cat_wallet(
            wallet_node_maker.wallet_state_manager,
            wallet_maker,
            {"identifier": "genesis_by_id"},
            xch_to_cat_amount,
            action_scope,
        )

    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)

    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
    maker_funds -= xch_to_cat_amount
    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

    chia_for_cat: OfferSummary = {
        wallet_maker.id(): 2,
        cat_wallet_maker.id(): -2,
    }
    cat_for_chia: OfferSummary = {
        wallet_maker.id(): -1,
        cat_wallet_maker.id(): 1,
    }

    trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        success, trade_make_1, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat, action_scope)
    await time_out_assert(10, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make_1)
    assert error is None
    assert success is True
    assert trade_make_1 is not None
    async with trade_manager_maker.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=False) as action_scope:
        success, trade_make_2, error = await trade_manager_maker.create_offer_for_ids(cat_for_chia, action_scope)
    await time_out_assert(10, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make_2)
    assert error is None
    assert success is True
    assert trade_make_2 is not None

    [offer_1], signing_response_1 = await wallet_node_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make_1.offer)]
    )
    [offer_2], signing_response_2 = await wallet_node_maker.wallet_state_manager.sign_offers(
        [Offer.from_bytes(trade_make_2.offer)]
    )
    agg_offer = Offer.aggregate([offer_1, offer_2])

    peer = wallet_node_taker.get_full_node_peer()
    async with trade_manager_taker.wallet_state_manager.new_action_scope(
        DEFAULT_TX_CONFIG, push=True, additional_signing_responses=[*signing_response_1, *signing_response_2]
    ) as action_scope:
        await trade_manager_taker.respond_to_offer(
            agg_offer,
            peer,
            action_scope,
        )

    await full_node.process_transaction_records(records=action_scope.side_effects.transactions)
    await full_node.wait_for_wallets_synced(wallet_nodes=[wallet_node_maker, wallet_node_taker], timeout=60)

    await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds + 1)
    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, maker_funds + 1)
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount - 1)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount - 1)
