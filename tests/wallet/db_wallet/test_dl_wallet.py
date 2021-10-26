import asyncio
import pytest
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from tests.setup_nodes import setup_simulators_and_wallets
from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.types.blockchain_format.program import Program
from blspy import AugSchemeMPL
from chia.types.spend_bundle import SpendBundle
from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from tests.time_out_assert import time_out_assert
from chia.wallet.util.merkle_tree import MerkleTree


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestDLWallet:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 3, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes_five_freeze(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_sim_two_wallets(self):
        async for _ in setup_simulators_and_wallets(3, 2, {}):
            yield _

    @pytest.mark.asyncio
    async def test_update_coin(self, three_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]
        wallet_node_2, server_2 = wallets[2]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet_0.get_new_puzzlehash()
        ph1 = await wallet_1.get_new_puzzlehash()
        ph2 = await wallet_2.get_new_puzzlehash()

        await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        # Wallet1 sets up DIDWallet1 without any backup set
        async with wallet_node_0.wallet_state_manager.lock:
            dl_wallet_0: DataLayerWallet = await DataLayerWallet.create_new_dl_wallet(
                wallet_node_0.wallet_state_manager, wallet_0, uint64(101), current_root
            )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, dl_wallet_0.get_confirmed_balance, 101)
        await time_out_assert(15, dl_wallet_0.get_unconfirmed_balance, 101)

        assert dl_wallet_0.dl_info.root_hash == current_root

        nodes.append(Program.to("beep").get_tree_hash())
        new_merkle_tree = MerkleTree(nodes)
        await dl_wallet_0.create_update_state_spend(new_merkle_tree.calculate_root())

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, dl_wallet_0.get_confirmed_balance, 101)
        await time_out_assert(15, dl_wallet_0.get_unconfirmed_balance, 101)

        assert dl_wallet_0.dl_info.root_hash == new_merkle_tree.calculate_root()
