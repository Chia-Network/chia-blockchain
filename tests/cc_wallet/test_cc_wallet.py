import asyncio
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
from src.wallet.wallet_coin_record import WalletCoinRecord
from tests.time_out_assert import time_out_assert
from typing import List


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestCCWallet:
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
    async def test_colour_creation(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, 4):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, 4 - 2)
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

    @pytest.mark.asyncio
    async def test_cc_spend(self, two_wallet_nodes):
        num_blocks = 8
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, 4):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, 4 - 2)
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

        cc_2_hash = await cc_wallet_2.get_new_inner_hash()
        await cc_wallet.cc_spend(uint64(60), cc_2_hash)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cc_wallet.get_confirmed_balance, 40)
        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 40)

        await time_out_assert(30, cc_wallet_2.get_confirmed_balance, 60)
        await time_out_assert(30, cc_wallet_2.get_unconfirmed_balance, 60)

        cc_hash = await cc_wallet.get_new_inner_hash()
        await cc_wallet_2.cc_spend(uint64(15), cc_hash)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cc_wallet.get_confirmed_balance, 55)
        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 55)

    @pytest.mark.asyncio
    async def test_get_wallet_for_colour(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, 4):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, 4 - 2)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

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
        for i in range(1, 4):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, 4 - 2)
            ]
        )
        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        ph = await wallet2.get_new_puzzlehash()
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

    @pytest.mark.asyncio
    async def test_cc_spend_uncoloured(self, two_wallet_nodes):
        num_blocks = 8
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, 4):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, 4 - 2)
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

        cc_2_hash = await cc_wallet_2.get_new_inner_hash()
        await cc_wallet.cc_spend(uint64(60), cc_2_hash)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cc_wallet.get_confirmed_balance, 40)
        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 40)

        await time_out_assert(15, cc_wallet_2.get_confirmed_balance, 60)
        await time_out_assert(15, cc_wallet_2.get_unconfirmed_balance, 60)

        cc2_ph = await cc_wallet_2.get_new_cc_puzzle_hash()
        spend_bundle = await wallet.wallet_state_manager.main_wallet.generate_signed_transaction(
            10, cc2_ph, 0
        )
        await wallet.wallet_state_manager.main_wallet.push_transaction(spend_bundle)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        id = cc_wallet_2.wallet_info.id
        wsm = cc_wallet_2.wallet_state_manager
        await self.time_out_assert(15, wsm.get_confirmed_balance_for_wallet, 70, id)
        await self.time_out_assert(15, cc_wallet_2.get_confirmed_balance, 60)
        await self.time_out_assert(15, cc_wallet_2.get_unconfirmed_balance, 60)
