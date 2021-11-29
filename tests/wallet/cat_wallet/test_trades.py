import asyncio
from pathlib import Path
from secrets import token_bytes

import pytest

from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.trade_manager import TradeManager
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


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
        await asyncio.sleep(1)

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
        success, trade_make, error = await trade_manager_maker.create_offer_for_ids(chia_for_cat)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_make is not None
        success, trade_take, error = await trade_manager_taker.respond_to_offer(Offer.from_bytes(trade_make.offer))
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert trade_take is not None

        MAKER_CHIA_BALANCE -= 1
        MAKER_NEW_CAT_BALANCE += 2
        TAKER_CHIA_BALANCE += 1
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

    @pytest.mark.asyncio
    async def test_cat_trade_with_multiple_asset_ids(self, wallets_prefarm):
        # This test start with CATWallet in both wallets. wall
        # wallet1 {wallet_id: 2 = 70}
        # wallet2 {wallet_id: 2 = 30}

        wallet_node_a, wallet_node_b, full_node = wallets_prefarm
        wallet_a = wallet_node_a.wallet_state_manager.main_wallet
        wallet_b = wallet_node_b.wallet_state_manager.main_wallet

        # cat_a_2 = CAT, Alice, wallet id = 2
        cat_a_2 = wallet_node_a.wallet_state_manager.wallets[2]
        cat_b_2 = wallet_node_b.wallet_state_manager.wallets[2]

        cat_a_3: CATWallet = await CATWallet.create_new_cat_wallet(
            wallet_node_a.wallet_state_manager, wallet_a, {"identifier": "genesis_by_id"}, uint64(100)
        )
        await asyncio.sleep(1)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cat_a_3.get_confirmed_balance, 100)
        await time_out_assert(15, cat_a_3.get_unconfirmed_balance, 100)

        # store these for asserting change later
        cat_balance = await cat_a_2.get_unconfirmed_balance()
        cat_balance_2 = await cat_b_2.get_unconfirmed_balance()

        assert cat_a_3.cat_info.my_tail is not None
        red = cat_a_3.get_asset_id()

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        cat_b_3: CATWallet = await CATWallet.create_wallet_for_cat(wallet_node_b.wallet_state_manager, wallet_b, red)
        await asyncio.sleep(1)

        assert cat_a_3.cat_info.my_tail == cat_b_3.cat_info.my_tail

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        trade_manager_0 = wallet_node_a.wallet_state_manager.trade_manager
        trade_manager_1 = wallet_node_b.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        # Wallet
        offer_dict = {1: 1000, 2: -20, 4: -50}

        success, trade_offer, error = await trade_manager_0.create_offer_for_ids(offer_dict, file)
        await asyncio.sleep(1)

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_1.get_discrepancies_for_offer(file_path)
        await asyncio.sleep(1)
        assert error is None
        assert success is True
        assert offer is not None
        assert offer["chia"] == -1000

        asset_id_2 = cat_a_2.get_asset_id()
        asset_id_3 = cat_a_3.get_asset_id()

        assert offer[asset_id_2] == 20
        assert offer[asset_id_3] == 50

        success, trade, reason = await trade_manager_1.respond_to_offer(file_path)
        await asyncio.sleep(1)

        assert success is True
        for i in range(0, 10):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cat_b_3.get_confirmed_balance, 50)
        await time_out_assert(15, cat_b_3.get_unconfirmed_balance, 50)

        await time_out_assert(15, cat_a_3.get_confirmed_balance, 50)
        await time_out_assert(15, cat_a_3.get_unconfirmed_balance, 50)

        await time_out_assert(15, cat_a_2.get_unconfirmed_balance, cat_balance - offer[asset_id_2])
        await time_out_assert(15, cat_b_2.get_unconfirmed_balance, cat_balance_2 + offer[asset_id_2])

        trade = await trade_manager_0.get_trade_by_id(trade_offer.trade_id)

        status: TradeStatus = TradeStatus(trade.status)

        assert status is TradeStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_cat_trade_cancel_insecure(self, wallets_prefarm):
        # Wallet A              Wallet B
        # CATWallet id 2: 50     CATWallet id 2: 50
        # CATWallet id 3: 50     CATWallet id 3: 50
        # CATWallet id 4: 40     CATWallet id 4: 60
        # Wallet A will create offer, cancel it by deleting from db only
        wallet_node_a, wallet_node_b, full_node = wallets_prefarm
        wallet_a = wallet_node_a.wallet_state_manager.main_wallet
        trade_manager_a: TradeManager = wallet_node_a.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        spendable_chia = await wallet_a.get_spendable_balance()

        offer_dict = {1: 10, 2: -30, 3: 30}

        success, trade_offer, error = await trade_manager_a.create_offer_for_ids(offer_dict, file)
        await asyncio.sleep(1)

        spendable_chia_after = await wallet_a.get_spendable_balance()

        locked_coin = await trade_manager_a.get_locked_coins(wallet_a.id())
        locked_sum = 0
        for name, record in locked_coin.items():
            locked_sum += record.coin.amount

        assert spendable_chia == spendable_chia_after + locked_sum
        assert success is True
        assert trade_offer is not None

        # Cancel offer 1 by just deleting from db
        await trade_manager_a.cancel_pending_offer(trade_offer.trade_id)
        await asyncio.sleep(1)
        spendable_after_cancel_1 = await wallet_a.get_spendable_balance()

        # Spendable should be the same as it was before making offer 1
        assert spendable_chia == spendable_after_cancel_1

        trade_a = await trade_manager_a.get_trade_by_id(trade_offer.trade_id)
        assert trade_a is not None
        assert trade_a.status == TradeStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_cat_trade_cancel_secure(self, wallets_prefarm):
        # Wallet A              Wallet B
        # CATWallet id 2: 50     CATWallet id 2: 50
        # CATWallet id 3: 50     CATWallet id 3: 50
        # CATWallet id 4: 40     CATWallet id 4: 60
        # Wallet A will create offer, cancel it by spending coins back to self

        wallet_node_a, wallet_node_b, full_node = wallets_prefarm
        wallet_a = wallet_node_a.wallet_state_manager.main_wallet
        trade_manager_a: TradeManager = wallet_node_a.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        spendable_chia = await wallet_a.get_spendable_balance()

        offer_dict = {1: 10, 2: -30, 3: 30}

        success, trade_offer, error = await trade_manager_a.create_offer_for_ids(offer_dict, file)
        await asyncio.sleep(1)

        spendable_chia_after = await wallet_a.get_spendable_balance()

        locked_coin = await trade_manager_a.get_locked_coins(wallet_a.id())
        locked_sum = 0
        for name, record in locked_coin.items():
            locked_sum += record.coin.amount

        assert spendable_chia == spendable_chia_after + locked_sum
        assert success is True
        assert trade_offer is not None

        # Cancel offer 1 by spending coins that were offered
        await trade_manager_a.cancel_pending_offer_safely(trade_offer.trade_id)
        await asyncio.sleep(1)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, wallet_a.get_spendable_balance, spendable_chia)

        # Spendable should be the same as it was before making offer 1

        async def get_status():
            assert trade_offer is not None
            trade_a = await trade_manager_a.get_trade_by_id(trade_offer.trade_id)
            assert trade_a is not None
            return trade_a.status

        await time_out_assert(15, get_status, TradeStatus.CANCELLED.value)
