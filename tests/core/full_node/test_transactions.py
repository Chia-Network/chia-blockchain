import asyncio
from secrets import token_bytes
from typing import Optional

import pytest

from src.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from src.consensus.block_record import BlockRecord
from src.full_node.full_node_api import FullNodeAPI
from src.protocols import full_node_protocol
from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32
from tests.setup_nodes import setup_simulators_and_wallets, self_hostname
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestTransactions:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_nodes_two_wallets(self):
        async for _ in setup_simulators_and_wallets(3, 2, {}):
            yield _

    @pytest.mark.asyncio
    async def test_wallet_coinbase(self, wallet_node):
        num_blocks = 5
        full_nodes, wallets = wallet_node
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        # funds += calculate_base_farmer_reward(0)
        await asyncio.sleep(2)
        print(await wallet.get_confirmed_balance(), funds)
        await time_out_assert(10, wallet.get_confirmed_balance, funds)

    @pytest.mark.asyncio
    async def test_tx_propagation(self, three_nodes_two_wallets):
        num_blocks = 5
        full_nodes, wallets = three_nodes_two_wallets

        wallet_0, wallet_server_0 = wallets[0]
        wallet_1, wallet_server_1 = wallets[1]
        full_node_api_0 = full_nodes[0]
        server_0 = full_node_api_0.server
        full_node_api_1 = full_nodes[1]
        server_1 = full_node_api_1.server
        full_node_api_2 = full_nodes[2]
        server_2 = full_node_api_2.server

        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()
        ph1 = await wallet_1.wallet_state_manager.main_wallet.get_new_puzzlehash()

        #
        # wallet0 <-> sever0 <-> server1 <-> server2 <-> wallet1
        #
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)
        await server_0.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await server_1.start_client(PeerInfo(self_hostname, uint16(server_2._port)), None)
        await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(server_2._port)), None)

        for i in range(num_blocks):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        await time_out_assert(10, wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance, funds)

        async def peak_height(fna: FullNodeAPI):
            peak: Optional[BlockRecord] = fna.full_node.blockchain.get_peak()
            if peak is None:
                return -1
            peak_height = peak.height
            return peak_height

        await time_out_assert(10, peak_height, num_blocks, full_node_api_1)
        await time_out_assert(10, peak_height, num_blocks, full_node_api_2)

        tx = await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(10, ph1, 0)
        await wallet_0.wallet_state_manager.main_wallet.push_transaction(tx)

        await time_out_assert(
            10,
            full_node_api_0.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        await time_out_assert(
            10,
            full_node_api_1.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        await time_out_assert(
            10,
            full_node_api_2.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )

        # Farm another block
        for i in range(1, 8):
            await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )
        print(f"Funds: {funds}")
        await time_out_assert(
            10,
            wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance,
            (funds - 10),
        )
        await time_out_assert(15, wallet_1.wallet_state_manager.main_wallet.get_confirmed_balance, 10)

    @pytest.mark.asyncio
    async def test_mempool_tx_sync(self, three_nodes_two_wallets):
        num_blocks = 5
        full_nodes, wallets = three_nodes_two_wallets

        wallet_0, wallet_server_0 = wallets[0]
        full_node_api_0 = full_nodes[0]
        server_0 = full_node_api_0.server
        full_node_api_1 = full_nodes[1]
        server_1 = full_node_api_1.server
        full_node_api_2 = full_nodes[2]
        server_2 = full_node_api_2.server

        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()

        # wallet0 <-> sever0 <-> server1

        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)
        await server_0.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        for i in range(num_blocks):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        all_blocks = await full_node_api_0.get_all_full_blocks()

        for block in all_blocks:
            await full_node_api_2.full_node.respond_block(full_node_protocol.RespondBlock(block))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        await time_out_assert(10, wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance, funds)

        tx = await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(10, token_bytes(), 0)
        await wallet_0.wallet_state_manager.main_wallet.push_transaction(tx)

        await time_out_assert(
            10,
            full_node_api_0.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        await time_out_assert(
            10,
            full_node_api_1.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        await time_out_assert(
            10,
            full_node_api_2.full_node.mempool_manager.get_spendbundle,
            None,
            tx.name,
        )

        # make a final connection.
        # wallet0 <-> sever0 <-> server1 <-> server2

        await server_1.start_client(PeerInfo(self_hostname, uint16(server_2._port)), None)

        await time_out_assert(
            10,
            full_node_api_0.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        await time_out_assert(
            10,
            full_node_api_1.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        await time_out_assert(
            10,
            full_node_api_2.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
