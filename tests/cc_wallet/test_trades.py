import asyncio
import time
from pathlib import Path
from secrets import token_bytes

import pytest

from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32, uint64
from src.wallet.trade_manager import TradeManager
from tests.setup_nodes import setup_simulators_and_wallets
from src.consensus.block_rewards import calculate_base_fee, calculate_block_reward
from src.wallet.cc_wallet.cc_wallet import CCWallet
from src.wallet.cc_wallet import cc_wallet_puzzles


async def time_out_assert(timeout: int, function, value, arg=None):
    start = time.time()
    while time.time() - start < timeout:
        if arg is None:
            function_result = await function()
        else:
            function_result = await function(arg)
        if value == function_result:
            return
        await asyncio.sleep(1)
    assert False


class TestCCTrades:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(
            1, 2, {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes_five_freeze(self):
        async for _ in setup_simulators_and_wallets(
            1, 2, {"COINBASE_FREEZE_PERIOD": 5}
        ):
            yield _

    @pytest.fixture(scope="function")
    async def three_sim_two_wallets(self):
        async for _ in setup_simulators_and_wallets(
            3, 2, {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    @pytest.mark.asyncio
    async def test_cc_trade(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        ph2 = await wallet2.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)

        assert cc_wallet.cc_info.my_core is not None
        colour = cc_wallet_puzzles.get_genesis_from_core(cc_wallet.cc_info.my_core)

        cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node_2.wallet_state_manager, wallet2, colour
        )

        assert cc_wallet.cc_info.my_core == cc_wallet_2.cc_info.my_core

        await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        trade_manager_1 = await TradeManager.create(wallet_node.wallet_state_manager)
        trade_manager_2 = await TradeManager.create(wallet_node_2.wallet_state_manager)

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        offer_dict = {1: 10, 2: -30}

        success, trade_offer, error = await trade_manager_1.create_offer_for_ids(
            offer_dict, file
        )

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_2.get_discrepancies_for_offer(
            file_path
        )

        assert error is None
        assert success is True
        assert offer is not None

        assert offer["chia"] == -10
        assert offer[colour] == 30

        success, reason = await trade_manager_2.respond_to_offer(file_path)

        assert success is True

        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cc_wallet_2.get_confirmed_balance, 30)
        await time_out_assert(15, cc_wallet_2.get_unconfirmed_balance, 30)

    @pytest.mark.asyncio
    async def test_cc_trade_with_multiple_colours(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        ph2 = await wallet2.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        red_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, red_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, red_wallet.get_unconfirmed_balance, 100)

        assert red_wallet.cc_info.my_core is not None
        red = cc_wallet_puzzles.get_genesis_from_core(red_wallet.cc_info.my_core)

        await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))

        blue_wallet_2: CCWallet = await CCWallet.create_new_cc(
            wallet_node_2.wallet_state_manager, wallet2, uint64(150)
        )
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        assert blue_wallet_2.cc_info.my_core is not None
        blue = cc_wallet_puzzles.get_genesis_from_core(blue_wallet_2.cc_info.my_core)

        red_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node_2.wallet_state_manager, wallet2, red
        )

        assert red_wallet.cc_info.my_core == red_wallet_2.cc_info.my_core

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        blue_wallet: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node.wallet_state_manager, wallet, blue
        )

        assert blue_wallet.cc_info.my_core == blue_wallet_2.cc_info.my_core

        trade_manager_1 = await TradeManager.create(wallet_node.wallet_state_manager)
        trade_manager_2 = await TradeManager.create(wallet_node_2.wallet_state_manager)

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        await blue_wallet.generate_zero_val_coin()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        offer_dict = {1: -1000, 2: -30, 3: 50}

        success, trade_offer, error = await trade_manager_1.create_offer_for_ids(
            offer_dict, file
        )

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_2.get_discrepancies_for_offer(
            file_path
        )
        assert error is None
        assert success is True
        assert offer is not None
        assert offer["chia"] == 1000
        assert offer[red] == 30
        assert offer[blue] == -50

        success, reason = await trade_manager_2.respond_to_offer(file_path)

        assert success is True
        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, red_wallet_2.get_confirmed_balance, 30)
        await time_out_assert(15, red_wallet_2.get_unconfirmed_balance, 30)

        await time_out_assert(15, blue_wallet_2.get_confirmed_balance, 100)
        await time_out_assert(15, blue_wallet_2.get_unconfirmed_balance, 100)

        await time_out_assert(15, blue_wallet.get_confirmed_balance, 50)
        await time_out_assert(15, blue_wallet.get_unconfirmed_balance, 50)

        await time_out_assert(15, red_wallet.get_confirmed_balance, 70)
        await time_out_assert(15, red_wallet.get_unconfirmed_balance, 70)

    @pytest.mark.asyncio
    async def test_create_offer_with_zero_val(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        ph2 = await wallet2.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)
        await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)

        assert cc_wallet.cc_info.my_core is not None
        colour = cc_wallet_puzzles.get_genesis_from_core(cc_wallet.cc_info.my_core)

        cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node_2.wallet_state_manager, wallet2, colour
        )

        assert cc_wallet.cc_info.my_core == cc_wallet_2.cc_info.my_core

        await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        trade_manager_1 = await TradeManager.create(wallet_node.wallet_state_manager)
        trade_manager_2 = await TradeManager.create(wallet_node_2.wallet_state_manager)

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        offer_dict = {1: -10, 2: 30}

        success, spend_bundle, error = await trade_manager_2.create_offer_for_ids(
            offer_dict, file
        )

        assert success is True
        assert spend_bundle is not None

        success, offer, error = await trade_manager_1.get_discrepancies_for_offer(
            file_path
        )

        assert error is None
        assert success is True
        assert offer is not None

        assert offer["chia"] == 10
        assert offer[colour] == -30

        success, reason = await trade_manager_1.respond_to_offer(file_path)

        assert success is True

        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        await time_out_assert(15, cc_wallet_2.get_confirmed_balance, 30)
        await time_out_assert(15, cc_wallet_2.get_confirmed_balance, 30)

    @pytest.mark.asyncio
    async def test_cc_trade_history(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        ph2 = await wallet2.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)

        assert cc_wallet.cc_info.my_core is not None
        colour = cc_wallet_puzzles.get_genesis_from_core(cc_wallet.cc_info.my_core)

        cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node_2.wallet_state_manager, wallet2, colour
        )

        assert cc_wallet.cc_info.my_core == cc_wallet_2.cc_info.my_core

        await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        trade_manager_1 = await TradeManager.create(wallet_node.wallet_state_manager)
        trade_manager_2 = await TradeManager.create(wallet_node_2.wallet_state_manager)

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        offer_dict = {1: 10, 2: -30}

        success, trade_offer, error = await trade_manager_1.create_offer_for_ids(
            offer_dict, file
        )

        assert success is True
        assert trade_offer is not None

        success, offer, error = await trade_manager_1.get_discrepancies_for_offer(
            file_path
        )

        assert error is None
        assert success is True
        assert offer is not None

        assert offer["chia"] == -10
        assert offer[colour] == 30

        history = await trade_manager_1.get_current_trades()

        assert len(history.trades) == 1
        (
            success,
            history_offer,
            error,
        ) = await trade_manager_1.get_discrepancies_for_spend_bundle(history.trades[0])
        assert offer == history_offer

        file_1 = "test_offer_file_1.offer"
        file_path_1 = Path(file_1)

        if file_path_1.exists():
            file_path_1.unlink()

        offer_dict_1 = {1: 11, 2: -33}
        success, spend_bundle, error = await trade_manager_1.create_offer_for_ids(
            offer_dict_1, file_1
        )

        success, offer_1, error = await trade_manager_1.get_discrepancies_for_offer(
            file_path_1
        )

        history = await trade_manager_1.get_current_trades()

        assert len(history.trades) == 2
        (
            success,
            history_offer_1,
            error,
        ) = await trade_manager_1.get_discrepancies_for_spend_bundle(history.trades[1])
        assert history_offer_1 == offer_1
