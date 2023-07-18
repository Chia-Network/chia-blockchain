from __future__ import annotations

import asyncio
import dataclasses
from secrets import token_bytes
from typing import Dict, List

import pytest
from blspy import G2Element

from chia.consensus.cost_calculator import NPCResult
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType

buffer_blocks = 4


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
class TestCATTrades:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "reuse_puzhash",
        [True, False],
    )
    async def test_cat_trades(self, wallets_prefarm, reuse_puzhash: bool, softfork_height: uint32):
        (
            [wallet_node_maker, initial_maker_balance],
            [wallet_node_taker, initial_taker_balance],
            full_node,
        ) = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

        # Create two new CATs, one in each wallet
        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, uint64(100)
            )
            await asyncio.sleep(1)

        async with wallet_node_taker.wallet_state_manager.lock:
            new_cat_wallet_taker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_taker.wallet_state_manager, wallet_taker, {"identifier": "genesis_by_id"}, uint64(100)
            )
            await asyncio.sleep(1)

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(token_bytes())))
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, 100)
        await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, 100)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, 100)

        # Add the taker's CAT to the maker's wallet
        assert cat_wallet_maker.cat_info.my_tail is not None
        assert new_cat_wallet_taker.cat_info.my_tail is not None
        new_cat_wallet_maker: CATWallet = await CATWallet.get_or_create_wallet_for_cat(
            wallet_node_maker.wallet_state_manager, wallet_maker, new_cat_wallet_taker.get_asset_id()
        )

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
            driver_dict[asset_id] = PuzzleInfo(
                {
                    "type": AssetType.CAT.name,
                    "tail": "0x" + asset_id,
                }
            )

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
        await asyncio.sleep(1)
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
                    await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
                        uint32(1)
                    )
                ).index
            )
            assert (
                taker_unused_index
                == (
                    await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
                        uint32(1)
                    )
                ).index
            )
        else:
            assert (
                maker_unused_index
                < (
                    await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
                        uint32(1)
                    )
                ).index
            )
            assert (
                taker_unused_index
                < (
                    await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
                        uint32(1)
                    )
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
        await time_out_assert(15, assert_trade_tx_number, True, wallet_node_taker, trade_take.trade_id, 3)

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
        await time_out_assert(15, assert_trade_tx_number, True, wallet_node_taker, trade_take.trade_id, 2)

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
        await asyncio.sleep(1)
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

        second_offer = Offer.from_bytes(trade_take.offer)

        MAKER_CAT_BALANCE -= 5
        MAKER_NEW_CAT_BALANCE += 6
        TAKER_CAT_BALANCE += 5
        TAKER_NEW_CAT_BALANCE -= 6

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
        if reuse_puzhash:
            # Check if unused index changed
            assert (
                maker_unused_index
                == (
                    await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
                        uint32(1)
                    )
                ).index
            )
            assert (
                taker_unused_index
                == (
                    await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
                        uint32(1)
                    )
                ).index
            )
        else:
            assert (
                maker_unused_index
                < (
                    await wallet_maker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
                        uint32(1)
                    )
                ).index
            )
            assert (
                taker_unused_index
                < (
                    await wallet_taker.wallet_state_manager.puzzle_store.get_current_derivation_record_for_wallet(
                        uint32(1)
                    )
                ).index
            )

        # chia_for_multiple_cat
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(
            chia_for_multiple_cat,
            driver_dict=driver_dict,
        )
        await asyncio.sleep(1)
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
        await asyncio.sleep(1)
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
        await asyncio.sleep(1)
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

        # This tests an edge case where aggregated offers the include > 2 of the same kind of CAT
        # (and therefore are solved as a complete ring)
        bundle = Offer.aggregate([first_offer, second_offer, third_offer, fourth_offer, fifth_offer]).to_valid_spend()
        program = simple_solution_generator(bundle)
        result: NPCResult = get_name_puzzle_conditions(
            program, INFINITE_COST, mempool_mode=True, height=softfork_height, constants=DEFAULT_CONSTANTS
        )
        assert result.error is None

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
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None

        await trade_manager_maker.cancel_pending_offer(trade_make.trade_id)
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

        txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=fee)
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

        txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=uint64(0))
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
        txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=uint64(0))
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
