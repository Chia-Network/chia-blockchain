import asyncio
from secrets import token_bytes

import pytest

from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint64
from chia.wallet.cc_wallet.cc_wallet import CCWallet
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


async def tx_in_pool(mempool: MempoolManager, tx_id):
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
async def two_wallet_nodes():
    async for _ in setup_simulators_and_wallets(1, 2, {}):
        yield _


buffer_blocks = 4


@pytest.fixture(scope="module")
async def wallets_prefarm(two_wallet_nodes):
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

    await wallet_server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    await wallet_server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

    for i in range(0, farm_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph0))

    for i in range(0, farm_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

    for i in range(0, buffer):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

    return wallet_node_0, wallet_node_1, full_node_api


@pytest.mark.parametrize(
    "trusted",
    [True, False],
)
class TestCATTrades:
    @pytest.mark.asyncio
    async def test_cat_trades(self, wallets_prefarm, trusted):
        wallet_node_maker, wallet_node_taker, full_node = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_maker.config["trusted_peers"] = {full_node.server.node_id: full_node.server.node_id}
            wallet_node_taker.config["trusted_peers"] = {full_node.server.node_id: full_node.server.node_id}
        else:
            wallet_node_maker.config["trusted_peers"] = {}
            wallet_node_taker.config["trusted_peers"] = {}

        # Create two new CATs, one in each wallet
        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CCWallet = await CCWallet.create_new_cc_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, uint64(100)
            )
            await asyncio.sleep(1)

        async with wallet_node_taker.wallet_state_manager.lock:
            new_cat_wallet_taker: CCWallet = await CCWallet.create_new_cc_wallet(
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
        assert cat_wallet_maker.cc_info.my_genesis_checker is not None
        assert new_cat_wallet_taker.cc_info.my_genesis_checker is not None
        new_cat_wallet_maker: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node_maker.wallet_state_manager, wallet_maker, new_cat_wallet_taker.get_colour()
        )

        # Create the trade parameters
        MAKER_CHIA_BALANCE = await wallet_maker.get_confirmed_balance()
        MAKER_CAT_BALANCE = await cat_wallet_maker.get_confirmed_balance()
        MAKER_NEW_CAT_BALANCE = await new_cat_wallet_maker.get_confirmed_balance()
        TAKER_CHIA_BALANCE = await wallet_taker.get_confirmed_balance()
        TAKER_CAT_BALANCE = 0
        TAKER_NEW_CAT_BALANCE = await new_cat_wallet_taker.get_confirmed_balance()

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

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        cat_wallet_taker: CCWallet = await wallet_node_taker.wallet_state_manager.get_wallet_for_colour(
            cat_wallet_maker.get_colour()
        )

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
    async def test_trade_cancellation(self, wallets_prefarm, trusted):
        wallet_node_maker, wallet_node_taker, full_node = wallets_prefarm
        wallet_maker = wallet_node_maker.wallet_state_manager.main_wallet
        wallet_taker = wallet_node_taker.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_maker.config["trusted_peers"] = {full_node.server.node_id: full_node.server.node_id}
            wallet_node_taker.config["trusted_peers"] = {full_node.server.node_id: full_node.server.node_id}
        else:
            wallet_node_maker.config["trusted_peers"] = {}
            wallet_node_taker.config["trusted_peers"] = {}

        async with wallet_node_maker.wallet_state_manager.lock:
            cat_wallet_maker: CCWallet = await CCWallet.create_new_cc_wallet(
                wallet_node_maker.wallet_state_manager, wallet_maker, {"identifier": "genesis_by_id"}, uint64(100)
            )
            await asyncio.sleep(1)

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cat_wallet_maker.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet_maker.get_unconfirmed_balance, 100)

        MAKER_CHIA_BALANCE = await wallet_maker.get_confirmed_balance()
        MAKER_CAT_BALANCE = await cat_wallet_maker.get_confirmed_balance()
        TAKER_CHIA_BALANCE = await wallet_taker.get_confirmed_balance()

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

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, get_trade_and_status, TradeStatus.CANCELLED, trade_manager_maker, trade_make)
        # await time_out_assert(15, get_trade_and_status, TradeStatus.FAILED, trade_manager_taker, trade_take)

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
