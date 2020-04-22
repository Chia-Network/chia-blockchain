import asyncio
from pathlib import Path
from secrets import token_bytes

import pytest

from src.protocols import full_node_protocol
from src.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32, uint64
from src.wallet.trade_manager import TradeManager
from tests.setup_nodes import setup_simulators_and_wallets
from src.consensus.block_rewards import calculate_base_fee, calculate_block_reward
from src.wallet.cc_wallet.cc_wallet import CCWallet
from src.wallet.cc_wallet import cc_wallet_puzzles
from src.wallet.wallet_coin_record import WalletCoinRecord
from typing import List


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletSimulator:
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
    """
    @pytest.mark.asyncio
    async def test_colour_creation(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(5)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        assert await wallet.get_confirmed_balance() == funds

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(5)
        confirmed_balance = await cc_wallet.get_confirmed_balance()
        unconfirmed_balance = await cc_wallet.get_unconfirmed_balance()

        assert confirmed_balance == 100
        assert unconfirmed_balance == 100
    """
    @pytest.mark.asyncio
    async def test_cc_spend(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(5)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        assert await wallet.get_confirmed_balance() == funds

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(1)
        confirmed_balance = await cc_wallet.get_confirmed_balance()
        unconfirmed_balance = await cc_wallet.get_unconfirmed_balance()

        assert confirmed_balance == 100
        assert unconfirmed_balance == 100

        colour = cc_wallet_puzzles.get_genesis_from_core(cc_wallet.cc_info.my_core)

        cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node_2.wallet_state_manager, wallet2, colour
        )

        assert cc_wallet.cc_info.my_core == cc_wallet_2.cc_info.my_core

        cc_2_hash = await cc_wallet_2.get_new_inner_hash()
        await cc_wallet.cc_spend(uint64(60), cc_2_hash)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(5)
        confirmed_balance = await cc_wallet.get_confirmed_balance()
        unconfirmed_balance = await cc_wallet.get_unconfirmed_balance()

        assert confirmed_balance == 40
        assert unconfirmed_balance == 40

        confirmed_balance = await cc_wallet_2.get_confirmed_balance()
        unconfirmed_balance = await cc_wallet_2.get_unconfirmed_balance()

        assert confirmed_balance == 60
        assert unconfirmed_balance == 60

        cc_hash = await cc_wallet.get_new_inner_hash()
        await cc_wallet_2.cc_spend(uint64(15), cc_hash)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(5)
        confirmed_balance = await cc_wallet.get_confirmed_balance()
        unconfirmed_balance = await cc_wallet.get_unconfirmed_balance()

        assert confirmed_balance == 55
        assert unconfirmed_balance == 55
    """
    @pytest.mark.asyncio
    async def test_get_wallet_for_colour(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(5)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        assert await wallet.get_confirmed_balance() == funds

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        colour = await cc_wallet.get_colour()
        assert (
            await wallet_node.wallet_state_manager.get_wallet_for_colour(colour)
            == cc_wallet
        )
    """
    """
    @pytest.mark.asyncio
    async def test_generate_zero_val(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(5)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        assert await wallet.get_confirmed_balance() == funds

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        ph = await wallet2.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(5)
        confirmed_balance = await cc_wallet.get_confirmed_balance()
        unconfirmed_balance = await cc_wallet.get_unconfirmed_balance()

        assert confirmed_balance == 100
        assert unconfirmed_balance == 100

        colour = cc_wallet_puzzles.get_genesis_from_core(cc_wallet.cc_info.my_core)

        cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(
            wallet_node_2.wallet_state_manager, wallet2, colour
        )

        assert cc_wallet.cc_info.my_core == cc_wallet_2.cc_info.my_core

        await cc_wallet_2.generate_zero_val_coin()

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        unspent: List[WalletCoinRecord] = list(
            await cc_wallet_2.wallet_state_manager.get_spendable_coins_for_wallet(
                cc_wallet_2.wallet_info.id
            )
        )
        assert len(unspent) == 1
        assert unspent.pop().coin.amount == 0
    """
    """
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

        await asyncio.sleep(5)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        assert await wallet.get_confirmed_balance() == funds

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )
        cc_colour = cc_wallet.cc_info.my_colour_name

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(1)
        confirmed_balance = await cc_wallet.get_confirmed_balance()
        unconfirmed_balance = await cc_wallet.get_unconfirmed_balance()

        assert confirmed_balance == 100
        assert unconfirmed_balance == 100

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

        file = "test_offer_file"
        file_path = Path(file)

        if file_path.exists():
            file_path.unlink()

        offer_dict = {1: 10, 2: -30}
        success, spend_bundle = await trade_manager_1.create_offer_for_ids(
            offer_dict, file
        )

        assert success is True
        assert spend_bundle is not None
        trade_manager_1.write_offer_to_disk(file, spend_bundle)

        success, offer, error = await trade_manager_2.get_discrepancies_for_offer(file)

        assert error is None
        assert success is True
        assert offer is not None

        assert offer[None] == -10
        assert offer[cc_colour] == 30

        success = await trade_manager_2.respond_to_offer(file)

        assert success is True

        for i in range(0, 4):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        await asyncio.sleep(10)
        cc_2_confirmed_balance = await cc_wallet_2.get_confirmed_balance()
        cc_2_unconfirmed_balance = await cc_wallet_2.get_confirmed_balance()
        assert cc_2_confirmed_balance == 30
        assert cc_2_unconfirmed_balance == 30
    """
