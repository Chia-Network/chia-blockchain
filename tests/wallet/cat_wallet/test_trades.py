from __future__ import annotations

import dataclasses
from typing import Any, Dict, List

import pytest
from blspy import G2Element

from chia.consensus.cost_calculator import NPCResult
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.vc_wallet.cr_cat_drivers import ProofsChecker
from chia.wallet.vc_wallet.cr_cat_wallet import CRCATWallet
from chia.wallet.vc_wallet.vc_store import VCProofs
from chia.wallet.wallet_node import WalletNode
from tests.conftest import SOFTFORK_HEIGHTS
from tests.wallet.vc_wallet.test_vc_wallet import mint_cr_cat


async def claim_pending_approval_balance(
    client: WalletRpcClient,
    wallet_node: WalletNode,
    wallet: CATWallet,
    full_node_api: FullNodeSimulator,
    expected_pending_approval_balance: uint64,
    expected_new_balance: uint64,
) -> None:
    assert isinstance(wallet, CRCATWallet)
    await time_out_assert(15, wallet.get_pending_approval_balance, expected_pending_approval_balance)
    txs = await client.crcat_approve_pending(
        wallet.id(),
        expected_pending_approval_balance,
    )
    spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
    await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    await time_out_assert(15, wallet.get_confirmed_balance, expected_new_balance)
    await time_out_assert(15, wallet.get_pending_approval_balance, 0)
    await time_out_assert(15, wallet.get_unconfirmed_balance, expected_new_balance)


# This deliberate parameterization may at first look like we're neglecting quite a few cases.
# However, active_softfork_height is only used is the case where we test aggregation.
# We do not test aggregation in a number of cases because it's not correlated with a lot of these parameters.
# So to avoid the overhead of start up for identical tests, we only change the softfork param for the tests that use it.
# To pin down the behavior that we intend to eventually deprecate, it only gets one test case.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wallets_prefarm_services,trusted,reuse_puzhash,credential_restricted,active_softfork_height",
    [
        (1, True, True, True, SOFTFORK_HEIGHTS[0]),
        (1, True, True, False, SOFTFORK_HEIGHTS[0]),
        (1, True, False, True, SOFTFORK_HEIGHTS[0]),
        (1, False, True, True, SOFTFORK_HEIGHTS[0]),
        (1, False, False, False, SOFTFORK_HEIGHTS[0]),
        (1, False, True, False, SOFTFORK_HEIGHTS[0]),
        (1, False, False, True, SOFTFORK_HEIGHTS[0]),
        *((1, True, False, False, height) for height in SOFTFORK_HEIGHTS),
    ],
    indirect=["wallets_prefarm_services"],
)
async def test_cat_trades(
    wallets_prefarm_services,
    reuse_puzhash: bool,
    credential_restricted: bool,
    active_softfork_height: uint32,
):
    (
        [wallet_node_maker, initial_maker_balance],
        [wallet_node_taker, initial_taker_balance],
        [client_maker, client_taker],
        [_, _],
        full_node,
    ) = wallets_prefarm_services
    wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
    wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

    trusted = len(wallet_node_maker.config["trusted_peers"]) > 0

    # Because making/taking CR-CATs is asymetrical, approving the hacked together aggregation test will fail
    # The taker is "making" offers that it is approving with a VC which multiple actual makers would never do
    # This is really a test of CATOuterPuzzle anyways and is not correlated with any of our params
    test_aggregation = not credential_restricted and not reuse_puzhash and trusted

    # Create two new CATs, one in each wallet
    if credential_restricted:
        did_wallet_maker: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_maker.wallet_state_manager, wallet_maker, uint64(1)
        )
        did_wallet_taker: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_taker.wallet_state_manager, wallet_taker, uint64(1)
        )
        initial_maker_balance -= 1
        initial_taker_balance -= 1
        did_id_maker = bytes32.from_hexstr(did_wallet_maker.get_my_DID())
        did_id_taker = bytes32.from_hexstr(did_wallet_taker.get_my_DID())
        tx_list = [
            *await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet_maker.id()),
            *await wallet_node_taker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(did_wallet_taker.id()),
        ]
        for spend_bundle in (tx.spend_bundle for tx in tx_list if tx.spend_bundle is not None):
            await time_out_assert_not_none(5, full_node.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

        tail_maker: Program = Program.to([3, (1, "maker"), None, None])
        tail_taker: Program = Program.to([3, (1, "taker"), None, None])
        proofs_checker_maker: ProofsChecker = ProofsChecker(["foo", "bar"])
        proofs_checker_taker: ProofsChecker = ProofsChecker(["bar", "zap"])
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
        await full_node.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
        await full_node.wait_for_wallet_synced(wallet_node=wallet_node_maker, timeout=20)
        await full_node.wait_for_wallet_synced(wallet_node=wallet_node_taker, timeout=20)

        vc_record_maker, txs = await client_maker.vc_mint(
            did_id_maker, target_address=await wallet_maker.get_new_puzzlehash()
        )
        spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
        await time_out_assert_not_none(30, full_node.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
        vc_record_taker, txs = await client_taker.vc_mint(
            did_id_taker, target_address=await wallet_taker.get_new_puzzlehash()
        )
        spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
        await time_out_assert_not_none(30, full_node.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
        await full_node.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
        await full_node.wait_for_wallet_synced(wallet_node=wallet_node_maker, timeout=20)
        await full_node.wait_for_wallet_synced(wallet_node=wallet_node_taker, timeout=20)
        initial_maker_balance -= 1
        initial_taker_balance -= 1

        proofs_maker: VCProofs = VCProofs({"foo": "1", "bar": "1", "zap": "1"})
        proof_root_maker: bytes32 = proofs_maker.root()
        txs = await client_maker.vc_spend(
            vc_record_maker.vc.launcher_id,
            new_proof_hash=proof_root_maker,
        )
        spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
        await time_out_assert_not_none(5, full_node.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

        proofs_taker: VCProofs = VCProofs({"foo": "1", "bar": "1", "zap": "1"})
        proof_root_taker: bytes32 = proofs_taker.root()
        txs = await client_taker.vc_spend(
            vc_record_taker.vc.launcher_id,
            new_proof_hash=proof_root_taker,
        )
        spend_bundle = next(tx.spend_bundle for tx in txs if tx.spend_bundle is not None)
        await time_out_assert_not_none(5, full_node.full_node.mempool_manager.get_spendbundle, spend_bundle.name())
    else:
        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, uint64(100)
            )
            txs = await wallet_node_maker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(wallet_maker.id())
            assert len(txs) > 0
            for spend_bundle in (tx.spend_bundle for tx in txs if tx.spend_bundle is not None):
                await time_out_assert_not_none(
                    5, full_node.full_node.mempool_manager.get_spendbundle, spend_bundle.name()
                )

        async with wallet_node_taker.wallet_state_manager.lock:
            new_cat_wallet_taker = await CATWallet.create_new_cat_wallet(
                wallet_node_taker.wallet_state_manager, wallet_taker, {"identifier": "genesis_by_id"}, uint64(100)
            )
            txs = await wallet_node_taker.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(wallet_taker.id())
            for spend_bundle in (tx.spend_bundle for tx in txs if tx.spend_bundle is not None):
                await time_out_assert_not_none(
                    5, full_node.full_node.mempool_manager.get_spendbundle, spend_bundle.name()
                )

    if credential_restricted:
        assert isinstance(cat_wallet_maker, CRCATWallet)
        assert isinstance(new_cat_wallet_taker, CRCATWallet)

    await full_node.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))
    await full_node.wait_for_wallet_synced(wallet_node=wallet_node_maker, timeout=20)
    await full_node.wait_for_wallet_synced(wallet_node=wallet_node_taker, timeout=20)
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, 100)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, 100)
    await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, 100)
    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, 100)

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

    if credential_restricted:
        assert isinstance(new_cat_wallet_maker, CRCATWallet)

    # Create the trade parameters
    MAKER_CHIA_BALANCE = initial_maker_balance - 100
    TAKER_CHIA_BALANCE = initial_taker_balance - 100
    await time_out_assert(25, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE)
    await time_out_assert(25, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
    MAKER_CAT_BALANCE = 100
    MAKER_NEW_CAT_BALANCE = 0
    TAKER_CAT_BALANCE = 0
    TAKER_NEW_CAT_BALANCE = 100

    chia_for_cat = {
        wallet_maker.id(): -1,
        bytes.fromhex(new_cat_wallet_maker.get_asset_id()): 2,  # This is the CAT that the taker made
    }
    cat_for_chia = {
        wallet_maker.id(): 3,
        cat_wallet_maker.id(): -4,  # The taker has no knowledge of this CAT yet
    }
    cat_for_cat = {
        bytes.fromhex(cat_wallet_maker.get_asset_id()): -5,
        new_cat_wallet_maker.id(): 6,
    }
    chia_for_multiple_cat = {
        wallet_maker.id(): -7,
        cat_wallet_maker.id(): 8,
        new_cat_wallet_maker.id(): 9,
    }
    multiple_cat_for_chia = {
        wallet_maker.id(): 10,
        cat_wallet_maker.id(): -11,
        new_cat_wallet_maker.id(): -12,
    }
    chia_and_cat_for_cat = {
        wallet_maker.id(): -13,
        cat_wallet_maker.id(): -14,
        new_cat_wallet_maker.id(): 15,
    }

    driver_dict: Dict[str, PuzzleInfo] = {}
    for wallet in (cat_wallet_maker, new_cat_wallet_maker):
        asset_id: str = wallet.get_asset_id()
        driver_item: Dict[str, Any] = {
            "type": AssetType.CAT.name,
            "tail": "0x" + asset_id,
        }
        if credential_restricted:
            driver_item["also"] = {
                "type": AssetType.CR.name,
                "authorized_providers": ["0x" + provider.hex() for provider in authorized_providers],
                "proofs_checker": proofs_checker_maker.as_program()
                if wallet == cat_wallet_maker
                else proofs_checker_taker.as_program(),
            }
        driver_dict[asset_id] = PuzzleInfo(driver_item)

    trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
    trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager
    maker_unused_index = (
        await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
    ).index
    taker_unused_index = (
        await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
    ).index
    # Execute all of the trades
    # chia_for_cat
    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        chia_for_cat, fee=uint64(1), reuse_puzhash=reuse_puzhash
    )
    assert error is None
    assert success is True
    assert trade_make is not None

    peer = wallet_node_taker.get_full_node_peer()
    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer),
        peer,
        fee=uint64(1),
        reuse_puzhash=reuse_puzhash,
    )
    assert trade_take is not None
    assert tx_records is not None

    if test_aggregation:
        first_offer = Offer.from_bytes(trade_take.offer)

    MAKER_CHIA_BALANCE -= 2  # -1 and -1 for fee
    MAKER_NEW_CAT_BALANCE += 2
    TAKER_CHIA_BALANCE += 0  # +1 and -1 for fee
    TAKER_NEW_CAT_BALANCE -= 2

    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)

    await full_node.process_transaction_records(records=tx_records)
    await full_node.wait_for_wallets_synced(wallet_nodes=[wallet_node_maker, wallet_node_taker], timeout=15)

    await time_out_assert(15, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE)
    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, MAKER_CHIA_BALANCE)
    if credential_restricted:
        await claim_pending_approval_balance(
            client_maker,
            wallet_node_maker,
            new_cat_wallet_maker,
            full_node,
            uint64(2),
            uint64(MAKER_NEW_CAT_BALANCE),
        )
    await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, wallet_taker.get_confirmed_balance, TAKER_CHIA_BALANCE)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
    if reuse_puzhash:
        # Check if unused index changed
        assert (
            maker_unused_index
            == (
                await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
        assert (
            taker_unused_index
            == (
                await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
    else:
        assert (
            maker_unused_index
            < (
                await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
        assert (
            taker_unused_index
            < (
                await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )

    async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
        trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
        return TradeStatus(trade_rec.status)

    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    async def assert_trade_tx_number(wallet_node, trade_id, number):
        txs = await wallet_node.wallet_state_manager.tx_store.get_transactions_by_trade_id(trade_id)
        return len(txs) == number

    await time_out_assert(15, assert_trade_tx_number, True, wallet_node_maker, trade_make.trade_id, 1)
    # CR-CATs will also have a TX record for the VC
    await time_out_assert(
        15, assert_trade_tx_number, True, wallet_node_taker, trade_take.trade_id, 4 if credential_restricted else 3
    )

    # cat_for_chia
    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_chia)
    assert error is None
    assert success is True
    assert trade_make is not None

    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer),
        peer,
    )
    assert trade_take is not None
    assert tx_records is not None

    MAKER_CAT_BALANCE -= 4
    MAKER_CHIA_BALANCE += 3
    TAKER_CAT_BALANCE += 4
    TAKER_CHIA_BALANCE -= 3

    cat_wallet_taker: CATWallet = await wallet_node_taker.wallet_state_manager.get_wallet_for_asset_id(
        cat_wallet_maker.get_asset_id()
    )
    if credential_restricted:
        assert isinstance(cat_wallet_taker, CRCATWallet)

    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

    await full_node.process_transaction_records(records=tx_records)
    await full_node.wait_for_wallets_synced(wallet_nodes=[wallet_node_maker, wallet_node_taker], timeout=15)

    await time_out_assert(15, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE)
    await time_out_assert(15, wallet_maker.get_unconfirmed_balance, MAKER_CHIA_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, wallet_taker.get_confirmed_balance, TAKER_CHIA_BALANCE)
    await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    await time_out_assert(15, assert_trade_tx_number, True, wallet_node_maker, trade_make.trade_id, 1)
    await time_out_assert(
        15, assert_trade_tx_number, True, wallet_node_taker, trade_take.trade_id, 3 if credential_restricted else 2
    )

    # cat_for_cat
    maker_unused_index = (
        await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
    ).index
    taker_unused_index = (
        await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
    ).index
    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        cat_for_cat, reuse_puzhash=reuse_puzhash
    )
    assert error is None
    assert success is True
    assert trade_make is not None
    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer),
        peer,
        reuse_puzhash=reuse_puzhash,
    )
    await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
    assert trade_take is not None
    assert tx_records is not None

    if test_aggregation:
        second_offer = Offer.from_bytes(trade_take.offer)

    MAKER_CAT_BALANCE -= 5
    MAKER_NEW_CAT_BALANCE += 6
    TAKER_CAT_BALANCE += 5
    TAKER_NEW_CAT_BALANCE -= 6

    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

    await full_node.process_transaction_records(records=tx_records)
    await full_node.wait_for_wallets_synced(wallet_nodes=[wallet_node_maker, wallet_node_taker], timeout=15)

    if credential_restricted:
        await claim_pending_approval_balance(
            client_maker,
            wallet_node_maker,
            new_cat_wallet_maker,
            full_node,
            uint64(6),
            uint64(MAKER_NEW_CAT_BALANCE),
        )
    await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)
    if reuse_puzhash:
        # Check if unused index changed
        assert (
            maker_unused_index
            == (
                await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
        assert (
            taker_unused_index
            == (
                await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
    else:
        assert (
            maker_unused_index
            < (
                await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )
        assert (
            taker_unused_index
            < (
                await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(uint32(1))
            ).index
        )

    # chia_for_multiple_cat
    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        chia_for_multiple_cat,
        driver_dict=driver_dict,
    )
    assert error is None
    assert success is True
    assert trade_make is not None

    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer),
        peer,
    )
    await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
    assert trade_take is not None
    assert tx_records is not None

    if test_aggregation:
        third_offer = Offer.from_bytes(trade_take.offer)

    MAKER_CHIA_BALANCE -= 7
    MAKER_CAT_BALANCE += 8
    MAKER_NEW_CAT_BALANCE += 9
    TAKER_CHIA_BALANCE += 7
    TAKER_CAT_BALANCE -= 8
    TAKER_NEW_CAT_BALANCE -= 9

    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

    await full_node.process_transaction_records(records=tx_records)
    await full_node.wait_for_wallets_synced(wallet_nodes=[wallet_node_maker, wallet_node_taker], timeout=15)

    if credential_restricted:
        await claim_pending_approval_balance(
            client_maker,
            wallet_node_maker,
            cat_wallet_maker,
            full_node,
            uint64(8),
            uint64(MAKER_CAT_BALANCE),
        )
        await claim_pending_approval_balance(
            client_maker,
            wallet_node_maker,
            new_cat_wallet_maker,
            full_node,
            uint64(9),
            uint64(MAKER_NEW_CAT_BALANCE),
        )
    await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    # multiple_cat_for_chia
    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        multiple_cat_for_chia,
    )
    assert error is None
    assert success is True
    assert trade_make is not None
    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer),
        peer,
    )
    await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
    assert trade_take is not None
    assert tx_records is not None

    if test_aggregation:
        fourth_offer = Offer.from_bytes(trade_take.offer)

    MAKER_CAT_BALANCE -= 11
    MAKER_NEW_CAT_BALANCE -= 12
    MAKER_CHIA_BALANCE += 10
    TAKER_CAT_BALANCE += 11
    TAKER_NEW_CAT_BALANCE += 12
    TAKER_CHIA_BALANCE -= 10

    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

    await full_node.process_transaction_records(records=tx_records)
    await full_node.wait_for_wallets_synced(wallet_nodes=[wallet_node_maker, wallet_node_taker], timeout=15)

    await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    # chia_and_cat_for_cat
    success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
        chia_and_cat_for_cat,
    )
    assert error is None
    assert success is True
    assert trade_make is not None

    trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        Offer.from_bytes(trade_make.offer),
        peer,
    )
    await time_out_assert(15, full_node.txs_in_mempool, True, tx_records)
    assert trade_take is not None
    assert tx_records is not None

    if test_aggregation:
        fifth_offer = Offer.from_bytes(trade_take.offer)

    MAKER_CHIA_BALANCE -= 13
    MAKER_CAT_BALANCE -= 14
    MAKER_NEW_CAT_BALANCE += 15
    TAKER_CHIA_BALANCE += 13
    TAKER_CAT_BALANCE += 14
    TAKER_NEW_CAT_BALANCE -= 15

    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

    await full_node.process_transaction_records(records=tx_records)
    await full_node.wait_for_wallets_synced(wallet_nodes=[wallet_node_maker, wallet_node_taker], timeout=15)

    if credential_restricted:
        await claim_pending_approval_balance(
            client_maker,
            wallet_node_maker,
            new_cat_wallet_maker,
            full_node,
            uint64(15),
            uint64(MAKER_NEW_CAT_BALANCE),
        )
    await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, MAKER_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_confirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
    await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

    if test_aggregation:
        # This tests an edge case where aggregated offers the include > 2 of the same kind of CAT
        # (and therefore are solved as a complete ring)
        bundle = Offer.aggregate([first_offer, second_offer, third_offer, fourth_offer, fifth_offer]).to_valid_spend()
        program = simple_solution_generator(bundle)
        result: NPCResult = get_name_puzzle_conditions(
            program, INFINITE_COST, mempool_mode=True, height=active_softfork_height, constants=DEFAULT_CONSTANTS
        )
        assert result.error is None


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
class TestCATTrades:
    @pytest.mark.asyncio
    async def test_trade_cancellation(self, wallets_prefarm):
        (
            [wallet_node_maker, maker_funds],
            [wallet_node_taker, taker_funds],
            full_node,
        ) = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

        xch_to_cat_amount = uint64(100)

        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, xch_to_cat_amount
            )

            tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()

        await full_node.process_transaction_records(records=tx_records)

        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
        maker_funds -= xch_to_cat_amount
        await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

        cat_for_chia = {
            wallet_maker.id(): 1,
            cat_wallet_maker.id(): -2,
        }

        chia_for_cat = {
            wallet_maker.id(): -3,
            cat_wallet_maker.id(): 4,
        }

        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
        trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

        async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
            trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
            return TradeStatus(trade_rec.status)

        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_chia)
        assert error is None
        assert success is True
        assert trade_make is not None

        # Cancelling the trade and trying an ID that doesn't exist just in case
        await trade_manager_maker.cancel_pending_offers([trade_make.trade_id, bytes32([0] * 32)], secure=False)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

        # Due to current mempool rules, trying to force a take out of the mempool with a cancel will not work.
        # Uncomment this when/if it does

        # trade_take, tx_records = await trade_manager_taker.respond_to_offer(
        #     Offer.from_bytes(trade_make.offer),
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

        txs = await trade_manager_maker.cancel_pending_offers([trade_make.trade_id], fee=fee, secure=True)
        await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
        await full_node.process_transaction_records(records=txs)

        sum_of_outgoing = uint64(0)
        sum_of_incoming = uint64(0)
        for tx in txs:
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
            await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer)

        # Now we're going to create the other way around for test coverage sake
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat)
        assert error is None
        assert success is True
        assert trade_make is not None

        # This take should fail since we have no CATs to fulfill it with
        with pytest.raises(
            ValueError,
            match=f"Do not have a wallet for asset ID: {cat_wallet_maker.get_asset_id()} to fulfill offer",
        ):
            await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer), peer)

        txs = await trade_manager_maker.cancel_pending_offers([trade_make.trade_id], fee=uint64(0), secure=True)
        await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
        await full_node.process_transaction_records(records=txs)

        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    @pytest.mark.asyncio
    async def test_trade_cancellation_balance_check(self, wallets_prefarm):
        (
            [wallet_node_maker, maker_funds],
            [wallet_node_taker, taker_funds],
            full_node,
        ) = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet

        xch_to_cat_amount = uint64(100)

        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, xch_to_cat_amount
            )

            tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()

        await full_node.process_transaction_records(records=tx_records)

        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
        maker_funds -= xch_to_cat_amount
        await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

        chia_for_cat = {
            wallet_maker.id(): -(await wallet_maker.get_spendable_balance()),
            cat_wallet_maker.id(): 4,
        }

        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager

        async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
            trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
            return TradeStatus(trade_rec.status)

        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat)
        await time_out_assert(10, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make)
        assert error is None
        assert success is True
        assert trade_make is not None
        txs = await trade_manager_maker.cancel_pending_offers([trade_make.trade_id], fee=uint64(0), secure=True)
        await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
        await full_node.process_transaction_records(records=txs)

        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    @pytest.mark.asyncio
    async def test_trade_conflict(self, three_wallets_prefarm):
        (
            [wallet_node_maker, maker_funds],
            [wallet_node_taker, taker_funds],
            [wallet_node_trader, trader_funds],
            full_node,
        ) = three_wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        xch_to_cat_amount = uint64(100)

        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, xch_to_cat_amount
            )

            tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()

        await full_node.process_transaction_records(records=tx_records)

        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
        maker_funds -= xch_to_cat_amount
        await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

        chia_for_cat = {
            wallet_maker.id(): 1000,
            cat_wallet_maker.id(): -4,
        }

        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
        trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager
        trade_manager_trader = wallet_node_trader.wallet_state_manager.trade_manager

        async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
            trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
            if trade_rec:
                return TradeStatus(trade_rec.status)
            raise ValueError("Couldn't find the trade record")

        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat)
        await time_out_assert(10, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make)
        assert error is None
        assert success is True
        assert trade_make is not None
        peer = wallet_node_taker.get_full_node_peer()
        offer = Offer.from_bytes(trade_make.offer)
        tr1, txs1 = await trade_manager_taker.respond_to_offer(offer, peer, fee=uint64(10))
        # we shouldn't be able to respond to a duplicate offer
        with pytest.raises(ValueError):
            await trade_manager_taker.respond_to_offer(offer, peer, fee=uint64(10))
        await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CONFIRM, trade_manager_taker, tr1)
        # pushing into mempool while already in it should fail
        tr2, txs2 = await trade_manager_trader.respond_to_offer(offer, peer, fee=uint64(10))
        assert await trade_manager_trader.get_coins_of_interest()
        offer_tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()
        await full_node.process_transaction_records(records=offer_tx_records)
        await time_out_assert(15, get_trade_and_status, TradeStatus.FAILED, trade_manager_trader, tr2)

    @pytest.mark.asyncio
    async def test_trade_bad_spend(self, wallets_prefarm):
        (
            [wallet_node_maker, maker_funds],
            [wallet_node_taker, taker_funds],
            full_node,
        ) = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        xch_to_cat_amount = uint64(100)

        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, xch_to_cat_amount
            )

            tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()

        await full_node.process_transaction_records(records=tx_records)

        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
        maker_funds -= xch_to_cat_amount
        await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

        chia_for_cat = {
            wallet_maker.id(): 1000,
            cat_wallet_maker.id(): -4,
        }

        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
        trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

        async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
            trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
            if trade_rec:
                return TradeStatus(trade_rec.status)
            raise ValueError("Couldn't find the trade record")

        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat)
        await time_out_assert(30, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make)
        assert error is None
        assert success is True
        assert trade_make is not None
        peer = wallet_node_taker.get_full_node_peer()
        offer = Offer.from_bytes(trade_make.offer)
        bundle = dataclasses.replace(offer._bundle, aggregated_signature=G2Element())
        offer = dataclasses.replace(offer, _bundle=bundle)
        tr1, txs1 = await trade_manager_taker.respond_to_offer(offer, peer, fee=uint64(10))
        wallet_node_taker.wallet_tx_resend_timeout_secs = 0  # don't wait for resend
        for _ in range(10):
            print(await wallet_node_taker._resend_queue())
        offer_tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()
        await full_node.process_transaction_records(records=offer_tx_records)
        await time_out_assert(30, get_trade_and_status, TradeStatus.FAILED, trade_manager_taker, tr1)

    @pytest.mark.asyncio
    async def test_trade_high_fee(self, wallets_prefarm):
        (
            [wallet_node_maker, maker_funds],
            [wallet_node_taker, taker_funds],
            full_node,
        ) = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        xch_to_cat_amount = uint64(100)

        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, xch_to_cat_amount
            )

            tx_records: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()

        await full_node.process_transaction_records(records=tx_records)

        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, xch_to_cat_amount)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, xch_to_cat_amount)
        maker_funds -= xch_to_cat_amount
        await time_out_assert(15, wallet_maker.get_confirmed_balance, maker_funds)

        chia_for_cat = {
            wallet_maker.id(): 1000,
            cat_wallet_maker.id(): -4,
        }

        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
        trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

        async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
            trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
            if trade_rec:
                return TradeStatus(trade_rec.status)
            raise ValueError("Couldn't find the trade record")

        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat)
        await time_out_assert(10, get_trade_and_status, TradeStatus.PENDING_ACCEPT, trade_manager_maker, trade_make)
        assert error is None
        assert success is True
        assert trade_make is not None
        peer = wallet_node_taker.get_full_node_peer()
        offer = Offer.from_bytes(trade_make.offer)
        tr1, txs1 = await trade_manager_taker.respond_to_offer(offer, peer, fee=uint64(1000000000000))
        await full_node.process_transaction_records(records=txs1)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, tr1)
