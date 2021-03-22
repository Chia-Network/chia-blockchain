import asyncio
import time
from pathlib import Path
from secrets import token_bytes

import pytest

from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint64
from chia.wallet.cc_wallet.cc_wallet import CCWallet
from chia.wallet.trade_manager import TradeManager
from chia.wallet.trading.trade_status import TradeStatus
from tests.setup_nodes import setup_simulators_and_wallets


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


async def time_out_assert(timeout: int, function, value, arg=None):
    start = time.time()
    while time.time() - start < timeout:
        if arg is None:
            function_result = await function()
        else:
            function_result = await function(arg)
        if value == function_result:
            return
        await asyncio.sleep(2)
    assert False


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


class TestCCTrades:
    @pytest.mark.asyncio
    async def test_cc_trade(self, wallets_prefarm):
        wallet_node_0, wallet_node_1, full_node = wallets_prefarm
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        cc_wallet: CCWallet = await CCWallet.create_new_cc(wallet_node_0.wallet_state_manager, wallet_0, uint64(100))

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)

        assert cc_wallet.cc_info.my_genesis_checker is not None
        colour = cc_wallet.get_colour()

        cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node_1.wallet_state_manager, wallet_1, colour
        )

        assert cc_wallet.cc_info.my_genesis_checker == cc_wallet_2.cc_info.my_genesis_checker

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        # send cc_wallet 2 a coin
        cc_hash = await cc_wallet_2.get_new_inner_hash()
        tx_record = await cc_wallet.generate_signed_transaction([uint64(1)], [cc_hash])
        await wallet_0.wallet_state_manager.add_pending_transaction(tx_record)
        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        trade_manager_0 = wallet_node_0.wallet_state_manager.trade_manager
        trade_manager_1 = wallet_node_1.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        offer_dict = {1: 10, 2: -30}

        success, trade_offer, error = await trade_manager_0.create_offer_for_ids(offer_dict, file)

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_1.get_discrepancies_for_offer(file_path)

        assert error is None
        assert success is True
        assert offer is not None

        assert offer["chia"] == -10
        assert offer[colour] == 30

        success, trade, reason = await trade_manager_1.respond_to_offer(file_path)

        assert success is True

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cc_wallet_2.get_confirmed_balance, 31)
        await time_out_assert(15, cc_wallet_2.get_unconfirmed_balance, 31)
        trade_2 = await trade_manager_0.get_trade_by_id(trade_offer.trade_id)
        assert TradeStatus(trade_2.status) is TradeStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_cc_trade_accept_with_zero(self, wallets_prefarm):
        wallet_node_0, wallet_node_1, full_node = wallets_prefarm
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        cc_wallet: CCWallet = await CCWallet.create_new_cc(wallet_node_0.wallet_state_manager, wallet_0, uint64(100))

        for i in range(1, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)

        assert cc_wallet.cc_info.my_genesis_checker is not None
        colour = cc_wallet.get_colour()

        cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node_1.wallet_state_manager, wallet_1, colour
        )

        assert cc_wallet.cc_info.my_genesis_checker == cc_wallet_2.cc_info.my_genesis_checker

        ph = await wallet_1.get_new_puzzlehash()
        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        trade_manager_0 = wallet_node_0.wallet_state_manager.trade_manager
        trade_manager_1 = wallet_node_1.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        offer_dict = {1: 10, 3: -30}

        success, trade_offer, error = await trade_manager_0.create_offer_for_ids(offer_dict, file)

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_1.get_discrepancies_for_offer(file_path)

        assert error is None
        assert success is True
        assert offer is not None

        assert cc_wallet.get_colour() == cc_wallet_2.get_colour()

        assert offer["chia"] == -10
        assert offer[colour] == 30

        success, trade, reason = await trade_manager_1.respond_to_offer(file_path)

        assert success is True

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cc_wallet_2.get_confirmed_balance, 30)
        await time_out_assert(15, cc_wallet_2.get_unconfirmed_balance, 30)
        trade_2 = await trade_manager_0.get_trade_by_id(trade_offer.trade_id)
        assert TradeStatus(trade_2.status) is TradeStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_cc_trade_with_multiple_colours(self, wallets_prefarm):
        # This test start with CCWallet in both wallets. wall
        # wallet1 {wallet_id: 2 = 70}
        # wallet2 {wallet_id: 2 = 30}

        wallet_node_a, wallet_node_b, full_node = wallets_prefarm
        wallet_a = wallet_node_a.wallet_state_manager.main_wallet
        wallet_b = wallet_node_b.wallet_state_manager.main_wallet

        # cc_a_2 = coloured coin, Alice, wallet id = 2
        cc_a_2 = wallet_node_a.wallet_state_manager.wallets[2]
        cc_b_2 = wallet_node_b.wallet_state_manager.wallets[2]

        cc_a_3: CCWallet = await CCWallet.create_new_cc(wallet_node_a.wallet_state_manager, wallet_a, uint64(100))

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cc_a_3.get_confirmed_balance, 100)
        await time_out_assert(15, cc_a_3.get_unconfirmed_balance, 100)

        # store these for asserting change later
        cc_balance = await cc_a_2.get_unconfirmed_balance()
        cc_balance_2 = await cc_b_2.get_unconfirmed_balance()

        assert cc_a_3.cc_info.my_genesis_checker is not None
        red = cc_a_3.get_colour()

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        cc_b_3: CCWallet = await CCWallet.create_wallet_for_cc(wallet_node_b.wallet_state_manager, wallet_b, red)

        assert cc_a_3.cc_info.my_genesis_checker == cc_b_3.cc_info.my_genesis_checker

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

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_1.get_discrepancies_for_offer(file_path)
        assert error is None
        assert success is True
        assert offer is not None
        assert offer["chia"] == -1000

        colour_2 = cc_a_2.get_colour()
        colour_3 = cc_a_3.get_colour()

        assert offer[colour_2] == 20
        assert offer[colour_3] == 50

        success, trade, reason = await trade_manager_1.respond_to_offer(file_path)

        assert success is True
        for i in range(0, 10):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cc_b_3.get_confirmed_balance, 50)
        await time_out_assert(15, cc_b_3.get_unconfirmed_balance, 50)

        await time_out_assert(15, cc_a_3.get_confirmed_balance, 50)
        await time_out_assert(15, cc_a_3.get_unconfirmed_balance, 50)

        await time_out_assert(15, cc_a_2.get_unconfirmed_balance, cc_balance - offer[colour_2])
        await time_out_assert(15, cc_b_2.get_unconfirmed_balance, cc_balance_2 + offer[colour_2])

        trade = await trade_manager_0.get_trade_by_id(trade_offer.trade_id)

        status: TradeStatus = TradeStatus(trade.status)

        assert status is TradeStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_create_offer_with_zero_val(self, wallets_prefarm):
        # Wallet A              Wallet B
        # CCWallet id 2: 50     CCWallet id 2: 50
        # CCWallet id 3: 50     CCWallet id 2: 50
        # Wallet A will
        # Wallet A will create a new CC and wallet B will create offer to buy that coin

        wallet_node_a, wallet_node_b, full_node = wallets_prefarm
        wallet_a = wallet_node_a.wallet_state_manager.main_wallet
        wallet_b = wallet_node_b.wallet_state_manager.main_wallet
        trade_manager_a: TradeManager = wallet_node_a.wallet_state_manager.trade_manager
        trade_manager_b: TradeManager = wallet_node_b.wallet_state_manager.trade_manager

        cc_a_4: CCWallet = await CCWallet.create_new_cc(wallet_node_a.wallet_state_manager, wallet_a, uint64(100))

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cc_a_4.get_confirmed_balance, 100)

        colour = cc_a_4.get_colour()

        cc_b_4: CCWallet = await CCWallet.create_wallet_for_cc(wallet_node_b.wallet_state_manager, wallet_b, colour)
        cc_balance = await cc_a_4.get_confirmed_balance()
        cc_balance_2 = await cc_b_4.get_confirmed_balance()
        offer_dict = {1: -30, cc_a_4.id(): 50}

        file = "test_offer_file.offer"
        file_path = Path(file)
        if file_path.exists():
            file_path.unlink()

        success, offer, error = await trade_manager_b.create_offer_for_ids(offer_dict, file)

        success, trade_a, reason = await trade_manager_a.respond_to_offer(file_path)

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
        await time_out_assert(15, cc_a_4.get_confirmed_balance, cc_balance - 50)
        await time_out_assert(15, cc_b_4.get_confirmed_balance, cc_balance_2 + 50)

        async def assert_func():
            assert trade_a is not None
            trade = await trade_manager_a.get_trade_by_id(trade_a.trade_id)
            assert trade is not None
            return trade.status

        async def assert_func_b():
            assert offer is not None
            trade = await trade_manager_b.get_trade_by_id(offer.trade_id)
            assert trade is not None
            return trade.status

        await time_out_assert(15, assert_func, TradeStatus.CONFIRMED.value)
        await time_out_assert(15, assert_func_b, TradeStatus.CONFIRMED.value)

    @pytest.mark.asyncio
    async def test_cc_trade_cancel_insecure(self, wallets_prefarm):
        # Wallet A              Wallet B
        # CCWallet id 2: 50     CCWallet id 2: 50
        # CCWallet id 3: 50     CCWallet id 3: 50
        # CCWallet id 4: 40     CCWallet id 4: 60
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
        spendable_after_cancel_1 = await wallet_a.get_spendable_balance()

        # Spendable should be the same as it was before making offer 1
        assert spendable_chia == spendable_after_cancel_1

        trade_a = await trade_manager_a.get_trade_by_id(trade_offer.trade_id)
        assert trade_a is not None
        assert trade_a.status == TradeStatus.CANCELED.value

    @pytest.mark.asyncio
    async def test_cc_trade_cancel_secure(self, wallets_prefarm):
        # Wallet A              Wallet B
        # CCWallet id 2: 50     CCWallet id 2: 50
        # CCWallet id 3: 50     CCWallet id 3: 50
        # CCWallet id 4: 40     CCWallet id 4: 60
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

        for i in range(0, buffer_blocks):
            await full_node.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, wallet_a.get_spendable_balance, spendable_chia)

        # Spendable should be the same as it was before making offer 1

        async def get_status():
            assert trade_offer is not None
            trade_a = await trade_manager_a.get_trade_by_id(trade_offer.trade_id)
            assert trade_a is not None
            return trade_a.status

        await time_out_assert(15, get_status, TradeStatus.CANCELED.value)
