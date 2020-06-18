import asyncio
import time
from pathlib import Path
from secrets import token_bytes
from typing import Optional

import pytest

from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32, uint64
from src.wallet.trading.trade_status import TradeStatus
from src.wallet.wallet_coin_record import WalletCoinRecord
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

        trade_manager_1 = wallet_node.wallet_state_manager.trade_manager
        trade_manager_2 = wallet_node_2.wallet_state_manager.trade_manager

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

        trade_manager_1 = wallet_node.wallet_state_manager.trade_manager
        trade_manager_2 = wallet_node_2.wallet_state_manager.trade_manager

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

        trade_manager_1 = wallet_node.wallet_state_manager.trade_manager
        trade_manager_2 = wallet_node_2.wallet_state_manager.trade_manager

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
    async def test_cc_trade_all(self, two_wallet_nodes):
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

        await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        trade_manager_1 = wallet_node.wallet_state_manager.trade_manager

        file = "test_offer_file.offer"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        spendable = await wallet.get_spendable_balance()
        offer_dict = {1: 10, 2: -30}

        success, trade_offer, error = await trade_manager_1.create_offer_for_ids(
            offer_dict, file
        )

        # Wallet spendable balance should be reduced by D[10] after creating this offer
        locked_coin = await trade_manager_1.get_locked_coins(wallet.wallet_info.id)
        locked_sum = 0
        for name, record in locked_coin.items():
            locked_sum += record.coin.amount
        spendable_after = await wallet.get_spendable_balance()
        assert spendable == spendable_after + locked_sum
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

        pending_offers = await trade_manager_1.get_offers_with_status(
            TradeStatus.PENDING_ACCEPT
        )
        pending_bundle = pending_offers[0].spend_bundle

        assert len(pending_offers) == 1
        (
            success,
            history_offer,
            error,
        ) = await trade_manager_1.get_discrepancies_for_spend_bundle(pending_bundle)
        assert offer == history_offer

        # Create another offer, we'll cancel this trade without spending coins
        file_1 = "test_offer_file_1.offer"
        file_path_1 = Path(file_1)

        if file_path_1.exists():
            file_path_1.unlink()

        spendable_before_offer_1 = await wallet.get_spendable_balance()

        offer_dict_1 = {1: 11, 2: -33}
        success, trade_offer_1, error = await trade_manager_1.create_offer_for_ids(
            offer_dict_1, file_1
        )

        assert success is True
        assert trade_offer_1 is not None
        assert error is None

        spendable_after_offer_1 = await wallet.get_spendable_balance()
        removal = trade_offer_1.spend_bundle.removals()
        locked_sum = 0
        for coin in removal:
            record: Optional[
                WalletCoinRecord
            ] = await trade_manager_1.wallet_state_manager.wallet_store.get_coin_record_by_coin_id(
                coin.name()
            )
            if record is None:
                continue
            if record.wallet_id == wallet.wallet_info.id:
                locked_sum += coin.amount

        assert spendable_before_offer_1 == spendable_after_offer_1 + locked_sum
        success, offer_1, error = await trade_manager_1.get_discrepancies_for_offer(
            file_path_1
        )

        pending_offers = await trade_manager_1.get_offers_with_status(
            TradeStatus.PENDING_ACCEPT
        )
        pending_bundle_1 = pending_offers[1].spend_bundle
        assert len(pending_offers) == 2
        (
            success,
            history_offer_1,
            error,
        ) = await trade_manager_1.get_discrepancies_for_spend_bundle(pending_bundle_1)
        assert history_offer_1 == offer_1

        # Cancel offer 1 by just deleting from db
        await trade_manager_1.cancel_pending_offer(pending_offers[1].trade_id)
        spendable_after_cancel_1 = await wallet.get_spendable_balance()

        # Spendable should be the same as it was before making offer 1
        assert spendable_before_offer_1 == spendable_after_cancel_1

        # Create offer 2, we'll cancel this offer securely by spending the offered coins

        file_2 = "test_offer_file_2.offer"
        file_path_2 = Path(file_1)

        if file_path_2.exists():
            file_path_2.unlink()

        spendable_before_offer_2 = await wallet.get_spendable_balance()

        offer_dict_2 = {1: 100, 2: -50}
        success, trade_offer_2, error = await trade_manager_1.create_offer_for_ids(
            offer_dict_2, file_2
        )

        spendable_after_offer_2 = await wallet.get_spendable_balance()
        removal = trade_offer_2.spend_bundle.removals()
        locked_sum_2 = 0
        for coin in removal:
            record: Optional[
                WalletCoinRecord
            ] = await trade_manager_1.wallet_state_manager.wallet_store.get_coin_record_by_coin_id(
                coin.name()
            )
            if record is None:
                continue
            if record.wallet_id == wallet.wallet_info.id:
                locked_sum_2 += coin.amount

        assert spendable_before_offer_2 == spendable_after_offer_2 + locked_sum_2

        # Cancel offer 2 by just doing a spend of coins in that offer

        spendable_before_secure_cancel = await wallet.get_spendable_balance()

        await trade_manager_1.cancel_pending_offer_safely(trade_offer_2.trade_id)

        spendable_after_secure_cancel = await wallet.get_spendable_balance()

        assert spendable_after_secure_cancel == spendable_before_secure_cancel

        for i in range(0, 4):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        await asyncio.sleep(1)

        spendable_after_cancel_confirmed = await wallet.get_spendable_balance()

        assert spendable_before_offer_1 == spendable_after_cancel_confirmed
