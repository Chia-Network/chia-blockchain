import asyncio
import dataclasses
from secrets import token_bytes
from typing import Callable, List, Tuple

import pytest
import pytest_asyncio
from blspy import G2Element

from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import ValidationError
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.payment import Payment
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from tests.pools.test_pool_rpc import wallet_is_synced
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


async def tx_in_pool(mempool: MempoolManager, tx_id):
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


@pytest_asyncio.fixture(scope="function")
async def two_wallet_nodes():
    async for _ in setup_simulators_and_wallets(1, 2, {}):
        yield _


buffer_blocks = 4


@pytest_asyncio.fixture(scope="function")
async def wallets_prefarm(two_wallet_nodes, self_hostname, trusted):
    """
    Sets up the node with 10 blocks, and returns a payer and payee wallet.
    """
    farm_blocks = 10
    buffer = 4
    full_nodes, wallets = two_wallet_nodes
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet_node_0, wallet_server_0 = wallets[0]
    wallet_node_1, wallet_server_1 = wallets[1]
    wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

    ph0 = await wallet_0.get_new_puzzlehash()
    ph1 = await wallet_1.get_new_puzzlehash()

    if trusted:
        wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
    else:
        wallet_node_0.config["trusted_peers"] = {}
        wallet_node_1.config["trusted_peers"] = {}

    await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

    for i in range(0, farm_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph0))

    for i in range(0, farm_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    for i in range(0, buffer):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

    await time_out_assert(10, wallet_is_synced, True, wallet_node_0, full_node_api)
    await time_out_assert(10, wallet_is_synced, True, wallet_node_1, full_node_api)

    return wallet_node_0, wallet_node_1, full_node_api


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
class TestCATTrades:
    @pytest.mark.asyncio
    async def test_cat_trades(self, wallets_prefarm):
        wallet_node_maker, wallet_node_taker, full_node = wallets_prefarm
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
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, 100)
        await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, 100)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, 100)

        # Add the taker's CAT to the maker's wallet
        assert cat_wallet_maker.cat_info.my_tail is not None
        assert new_cat_wallet_taker.cat_info.my_tail is not None
        new_cat_wallet_maker: CATWallet = await CATWallet.create_wallet_for_cat(
            wallet_node_maker.wallet_state_manager, wallet_maker, new_cat_wallet_taker.get_asset_id()
        )

        # Create the trade parameters
        MAKER_CHIA_BALANCE = 20 * 1000000000000 - 100
        TAKER_CHIA_BALANCE = 20 * 1000000000000 - 100
        await time_out_assert(25, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE)
        await time_out_assert(25, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
        MAKER_CAT_BALANCE = 100
        MAKER_NEW_CAT_BALANCE = 0
        TAKER_CAT_BALANCE = 0
        TAKER_NEW_CAT_BALANCE = 100

        chia_for_cat = {
            wallet_maker.id(): -1,
            new_cat_wallet_maker.id(): 2,  # This is the CAT that the taker made
        }
        cat_for_chia = {
            wallet_maker.id(): 3,
            cat_wallet_maker.id(): -4,  # The taker has no knowledge of this CAT yet
        }
        cat_for_cat = {
            cat_wallet_maker.id(): -5,
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

        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager
        trade_manager_taker = wallet_node_taker.wallet_state_manager.trade_manager

        # Execute all of the trades
        # chia_for_cat
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat, fee=uint64(1))
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None

        success, trade_take, error = await trade_manager_taker.respond_to_offer(
            Offer.from_bytes(trade_make.offer), fee=uint64(1)
        )
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_take is not None

        MAKER_CHIA_BALANCE -= 2  # -1 and -1 for fee
        MAKER_NEW_CAT_BALANCE += 2
        TAKER_CHIA_BALANCE += 0  # +1 and -1 for fee
        TAKER_NEW_CAT_BALANCE -= 2

        await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE)
        await time_out_assert(15, wallet_maker.get_unconfirmed_balance, MAKER_CHIA_BALANCE)
        await time_out_assert(15, new_cat_wallet_maker.get_confirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_maker.get_unconfirmed_balance, MAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, wallet_taker.get_confirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_confirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)

        async def get_trade_and_status(trade_manager, trade) -> TradeStatus:
            trade_rec = await trade_manager.get_trade_by_id(trade.trade_id)
            return TradeStatus(trade_rec.status)

        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_maker, trade_make)
        await time_out_assert(15, get_trade_and_status, TradeStatus.CONFIRMED, trade_manager_taker, trade_take)

        maker_txs = await wallet_node_maker.wallet_state_manager.tx_store.get_transactions_by_trade_id(
            trade_make.trade_id
        )
        taker_txs = await wallet_node_taker.wallet_state_manager.tx_store.get_transactions_by_trade_id(
            trade_take.trade_id
        )
        assert len(maker_txs) == 1  # The other side will show up as a regular incoming transaction
        assert len(taker_txs) == 3  # One for each: the outgoing CAT, the incoming chia, and the outgoing chia fee

        # cat_for_chia
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_chia)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None

        success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_take is not None

        MAKER_CAT_BALANCE -= 4
        MAKER_CHIA_BALANCE += 3
        TAKER_CAT_BALANCE += 4
        TAKER_CHIA_BALANCE -= 3

        cat_wallet_taker: CATWallet = await wallet_node_taker.wallet_state_manager.get_wallet_for_asset_id(
            cat_wallet_maker.get_asset_id()
        )

        await time_out_assert(15, wallet_taker.get_unconfirmed_balance, TAKER_CHIA_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

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

        maker_txs = await wallet_node_maker.wallet_state_manager.tx_store.get_transactions_by_trade_id(
            trade_make.trade_id
        )
        taker_txs = await wallet_node_taker.wallet_state_manager.tx_store.get_transactions_by_trade_id(
            trade_take.trade_id
        )
        assert len(maker_txs) == 1  # The other side will show up as a regular incoming transaction
        assert len(taker_txs) == 2  # One for each: the outgoing chia, the incoming CAT

        # cat_for_cat
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(cat_for_cat)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None
        success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_take is not None

        MAKER_CAT_BALANCE -= 5
        MAKER_NEW_CAT_BALANCE += 6
        TAKER_CAT_BALANCE += 5
        TAKER_NEW_CAT_BALANCE -= 6

        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

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

        # chia_for_multiple_cat
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_multiple_cat)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None
        success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_take is not None

        MAKER_CHIA_BALANCE -= 7
        MAKER_CAT_BALANCE += 8
        MAKER_NEW_CAT_BALANCE += 9
        TAKER_CHIA_BALANCE += 7
        TAKER_CAT_BALANCE -= 8
        TAKER_NEW_CAT_BALANCE -= 9

        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

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
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(multiple_cat_for_chia)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None
        success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_take is not None

        MAKER_CAT_BALANCE -= 11
        MAKER_NEW_CAT_BALANCE -= 12
        MAKER_CHIA_BALANCE += 10
        TAKER_CAT_BALANCE += 11
        TAKER_NEW_CAT_BALANCE += 12
        TAKER_CHIA_BALANCE -= 10

        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

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
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_and_cat_for_cat)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None
        success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_take is not None

        MAKER_CHIA_BALANCE -= 13
        MAKER_CAT_BALANCE -= 14
        MAKER_NEW_CAT_BALANCE += 15
        TAKER_CHIA_BALANCE += 13
        TAKER_CAT_BALANCE += 14
        TAKER_NEW_CAT_BALANCE -= 15

        await time_out_assert(15, new_cat_wallet_taker.get_unconfirmed_balance, TAKER_NEW_CAT_BALANCE)
        await time_out_assert(15, cat_wallet_taker.get_unconfirmed_balance, TAKER_CAT_BALANCE)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

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

    @pytest.mark.asyncio
    async def test_trade_cancellation(self, wallets_prefarm):
        wallet_node_maker, wallet_node_taker, full_node = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, uint64(100)
            )

            tx_queue: List[TransactionRecord] = await wallet_node_maker.wallet_state_manager.tx_store.get_not_sent()
            await time_out_assert(
                15, tx_in_pool, True, full_node.full_node.mempool_manager, tx_queue[0].spend_bundle.name()
            )

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, 100)
        MAKER_CHIA_BALANCE = 20 * 1000000000000 - 100
        MAKER_CAT_BALANCE = 100
        TAKER_CHIA_BALANCE = 20 * 1000000000000
        await time_out_assert(15, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE)

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

        # success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))
        # await asyncio.sleep(1)
        # assert error is None
        # assert success is True
        # assert trade_take is not None
        # await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CONFIRM, trade_manager_taker, trade_take)
        # await time_out_assert(
        #     15,
        #     tx_in_pool,
        #     True,
        #     full_node.full_node.mempool_manager,
        #     Offer.from_bytes(trade_take.offer).to_valid_spend().name(),
        # )

        FEE = uint64(2000000000000)

        txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=FEE)
        await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
        for tx in txs:
            if tx.spend_bundle is not None:
                await time_out_assert(15, tx_in_pool, True, full_node.full_node.mempool_manager, tx.spend_bundle.name())

        sum_of_outgoing = uint64(0)
        sum_of_incoming = uint64(0)
        for tx in txs:
            if tx.type == TransactionType.OUTGOING_TX.value:
                sum_of_outgoing = uint64(sum_of_outgoing + tx.amount)
            elif tx.type == TransactionType.INCOMING_TX.value:
                sum_of_incoming = uint64(sum_of_incoming + tx.amount)
        assert (sum_of_outgoing - sum_of_incoming) == 0

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)
        # await time_out_assert(15, get_trade_and_status, TradeStatus.FAILED, trade_manager_taker, trade_take)

        await time_out_assert(15, wallet_maker.get_pending_change_balance, 0)
        await time_out_assert(15, wallet_maker.get_confirmed_balance, MAKER_CHIA_BALANCE - FEE)
        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, MAKER_CAT_BALANCE)
        await time_out_assert(15, wallet_taker.get_confirmed_balance, TAKER_CHIA_BALANCE)

        success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))
        await asyncio.sleep(1)
        assert error is not None
        assert success is False
        assert trade_take is None

        # Now we're going to create the other way around for test coverage sake
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None

        # This take should fail since we have no CATs to fulfill it with
        success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))
        await asyncio.sleep(1)
        assert error is not None
        assert success is False
        assert trade_take is None

        txs = await trade_manager_maker.cancel_pending_offer_safely(trade_make.trade_id, fee=uint64(0))
        await time_out_assert(15, get_trade_and_status, TradeStatus.PENDING_CANCEL, trade_manager_maker, trade_make)
        for tx in txs:
            if tx.spend_bundle is not None:
                await time_out_assert(15, tx_in_pool, True, full_node.full_node.mempool_manager, tx.spend_bundle.name())

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)

    @pytest.mark.asyncio
    async def test_malicious_trades(self, wallets_prefarm):
        wallet_node_maker, _, full_node = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        trade_manager_maker = wallet_node_maker.wallet_state_manager.trade_manager

        ACS: Program = Program.to(1)
        ACS_PH: Program = ACS.get_tree_hash()

        # Fund an "anyone can spend" coin for use with these malicious trades
        tx = await wallet_maker.generate_signed_transaction(100, ACS_PH, 0)
        parent_acs_coin: Coin = next(c for c in tx.spend_bundle.additions() if c.amount == 100)
        # Spend it once so we have the previous one to try and double spend
        additional_spend = SpendBundle(
            [CoinSpend(parent_acs_coin, ACS, Program.to([[51, ACS_PH, parent_acs_coin.amount]]))], G2Element()
        )
        tx = dataclasses.replace(tx, spend_bundle=SpendBundle.aggregate([tx.spend_bundle, additional_spend]))
        await wallet_node_maker.wallet_state_manager.add_pending_transaction(tx)
        await time_out_assert(15, tx_in_pool, True, full_node.full_node.mempool_manager, tx.spend_bundle.name())

        for i in range(0, 2):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
            await asyncio.sleep(0.5)

        async def check_for_coin_creation(get_coin_state: Callable, coin: Coin):
            states = await get_coin_state([coin.name()])
            if len(states) > 0:
                return True
            else:
                return False

        acs_coin: Coin = next(c for c in tx.spend_bundle.additions() if c.amount == 100 and c != parent_acs_coin)
        await time_out_assert(15, check_for_coin_creation, True, wallet_node_maker.get_coin_state, acs_coin)

        # First let's test forgetting to offer or request something
        with pytest.raises(Exception, match="not requesting anything"):
            await trade_manager_maker.create_offer_for_ids({1: -100})
        with pytest.raises(Exception, match="not offering anything"):
            await trade_manager_maker.create_offer_for_ids({1: 100})

        # Next let's make an honest offer of the ACS for some imaginary CAT type
        honest_coin_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to([[51, Offer.ph(), acs_coin.amount]]),
        )
        requested_payments = Offer.notarize_payments({bytes32([0] * 32): [Payment(ACS_PH, 100, [])]}, [acs_coin])
        honest_offer = Offer(
            requested_payments,
            SpendBundle([honest_coin_spend], G2Element()),
        )
        assert await trade_manager_maker.check_offer_validity(honest_offer, raise_error=True)

        # Test bad aggregated_signature
        bad_agg_sig_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [50, wallet_node_maker.wallet_state_manager.private_key.get_g1(), b"$"],
                ]
            ),
        )
        bad_agg_sig_offer = Offer(
            requested_payments,
            SpendBundle([bad_agg_sig_spend], G2Element()),
        )
        with pytest.raises(ValidationError, match="BAD_AGGREGATE_SIGNATURE"):
            await trade_manager_maker.check_offer_validity(bad_agg_sig_offer, raise_error=True)

        # Test coin amount negative
        negative_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), -1],
                ]
            ),
        )
        with pytest.raises(ValueError, match="does not fit into uint64"):
            Offer(
                requested_payments,
                SpendBundle([negative_spend], G2Element()),
            )

        # Test more than maximum amount
        too_large_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), wallet_node_maker.wallet_state_manager.constants.MAX_COIN_AMOUNT + 1],
                ]
            ),
        )
        with pytest.raises(ValueError, match="does not fit into uint64"):
            Offer(
                requested_payments,
                SpendBundle([too_large_spend], G2Element()),
            )

        # Test duplicate outputs
        duplicate_output_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), 1],
                    [51, Offer.ph(), 1],
                ]
            ),
        )
        duplicate_output_offer = Offer(
            requested_payments,
            SpendBundle([duplicate_output_spend], G2Element()),
        )
        with pytest.raises(ValidationError, match="DUPLICATE_OUTPUT"):
            await trade_manager_maker.check_offer_validity(duplicate_output_offer, raise_error=True)

        # Test double spend
        double_spend_offer = Offer(
            requested_payments,
            SpendBundle([honest_coin_spend, honest_coin_spend], G2Element()),
        )
        with pytest.raises(ValidationError, match="DOUBLE_SPEND"):
            await trade_manager_maker.check_offer_validity(double_spend_offer, raise_error=True)

        # Test minting value
        minting_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to([[51, Offer.ph(), acs_coin.amount + 1]]),
        )
        minting_offer = Offer(
            requested_payments,
            SpendBundle([minting_spend], G2Element()),
        )
        with pytest.raises(ValidationError, match="MINTING_COIN"):
            await trade_manager_maker.check_offer_validity(minting_offer, raise_error=True)

        # Test invalid fee reservation
        bad_reserve_fee_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [52, 1],
                ]
            ),
        )
        bad_reserve_fee_offer = Offer(
            requested_payments,
            SpendBundle([bad_reserve_fee_spend], G2Element()),
        )
        with pytest.raises(ValidationError, match="RESERVE_FEE_CONDITION_FAILED"):
            await trade_manager_maker.check_offer_validity(bad_reserve_fee_offer, raise_error=True)

        # Test unknown unspent
        unknown_unspent_spend = CoinSpend(
            dataclasses.replace(acs_coin, parent_coin_info=bytes32([0] * 32)),
            ACS,
            Program.to([[51, Offer.ph(), acs_coin.amount]]),
        )
        unknown_unspent_offer = Offer(
            requested_payments,
            SpendBundle([unknown_unspent_spend], G2Element()),
        )
        with pytest.raises(ValidationError, match="UNKNOWN_UNSPENT"):
            await trade_manager_maker.check_offer_validity(unknown_unspent_offer, raise_error=True)

        # Test double spend
        double_spend = CoinSpend(
            parent_acs_coin,
            ACS,
            Program.to([[51, Offer.ph(), acs_coin.amount]]),
        )
        double_spend_offer = Offer(
            requested_payments,
            SpendBundle([double_spend], G2Element()),
        )
        with pytest.raises(ValidationError, match="DOUBLE_SPEND"):
            await trade_manager_maker.check_offer_validity(double_spend_offer, raise_error=True)

        # Test incorrect puzzle reveal
        wrong_ph_spend = CoinSpend(
            dataclasses.replace(acs_coin, puzzle_hash=bytes32([0] * 32)),
            ACS,
            Program.to([[51, Offer.ph(), acs_coin.amount]]),
        )
        wrong_ph_offer = Offer(
            requested_payments,
            SpendBundle([wrong_ph_spend], G2Element()),
        )
        with pytest.raises(ValidationError, match="INVALID_SPEND_BUNDLE"):
            await trade_manager_maker.check_offer_validity(wrong_ph_offer, raise_error=True)

        # Test a bunch of invalid conditions
        error_spend_items: List[Tuple[str, CoinSpend]] = []

        assert_coin_announcement_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [61, bytes32([0] * 32)],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_ANNOUNCE_CONSUMED_FAILED", assert_coin_announcement_spend))

        assert_puzzle_announcement_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [63, bytes32([0] * 32)],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_ANNOUNCE_CONSUMED_FAILED", assert_puzzle_announcement_spend))

        assert_my_coin_id_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [70, bytes32([0] * 32)],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_MY_COIN_ID_FAILED", assert_my_coin_id_spend))

        assert_my_parent_id_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [71, bytes32([0] * 32)],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_MY_PARENT_ID_FAILED", assert_my_parent_id_spend))

        assert_my_puzzle_hash_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [72, bytes32([0] * 32)],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_MY_PUZZLEHASH_FAILED", assert_my_puzzle_hash_spend))

        assert_my_amount_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [73, 0],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_MY_AMOUNT_FAILED", assert_my_amount_spend))

        max_uint64 = uint64(18446744073709551615)
        assert_seconds_relative_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [80, max_uint64],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_SECONDS_RELATIVE_FAILED", assert_seconds_relative_spend))

        assert_seconds_absolute_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [81, max_uint64],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_SECONDS_ABSOLUTE_FAILED", assert_seconds_absolute_spend))

        max_uint32 = uint32(4294967295)
        assert_height_relative_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [82, max_uint32],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_HEIGHT_RELATIVE_FAILED", assert_height_relative_spend))

        max_uint32 = uint32(4294967295)
        assert_height_absolute_spend = CoinSpend(
            acs_coin,
            ACS,
            Program.to(
                [
                    [51, Offer.ph(), acs_coin.amount],
                    [83, max_uint32],
                ]
            ),
        )
        error_spend_items.append(("ASSERT_HEIGHT_ABSOLUTE_FAILED", assert_height_absolute_spend))

        for error, spend in error_spend_items:
            error_offer = Offer(
                requested_payments,
                SpendBundle([spend], G2Element()),
            )
            with pytest.raises(ValidationError, match=error):
                await trade_manager_maker.check_offer_validity(error_offer, raise_error=True)
