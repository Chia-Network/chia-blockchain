import asyncio
from secrets import token_bytes
from typing import Optional

import pytest

from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32
from tests.setup_nodes import self_hostname, setup_simulators_and_wallets
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
        print(f" ==== test_tx_propagation A")
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

        print(f" ==== test_tx_propagation B")
        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()
        print(f" ==== test_tx_propagation C")
        ph1 = await wallet_1.wallet_state_manager.main_wallet.get_new_puzzlehash()
        print(f" ==== test_tx_propagation D")

        #
        # wallet0 <-> sever0 <-> server1 <-> server2 <-> wallet1
        #
        print(f" ==== test_tx_propagation E")
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)
        print(f" ==== test_tx_propagation F")
        await server_0.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        print(f" ==== test_tx_propagation G")
        await server_1.start_client(PeerInfo(self_hostname, uint16(server_2._port)), None)
        print(f" ==== test_tx_propagation H")
        await wallet_server_1.start_client(PeerInfo(self_hostname, uint16(server_2._port)), None)

        print(f" ==== test_tx_propagation I")
        for i in range(num_blocks):
            print(f" ==== test_tx_propagation I {i}")
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        print(f" ==== test_tx_propagation J")
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

        print(f" ==== test_tx_propagation K")
        await time_out_assert(10, peak_height, num_blocks, full_node_api_1)
        print(f" ==== test_tx_propagation L")
        await time_out_assert(10, peak_height, num_blocks, full_node_api_2)

        print(f" ==== test_tx_propagation M")
        tx = await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(10, ph1, 0)
        print(f" ==== test_tx_propagation N")
        await wallet_0.wallet_state_manager.main_wallet.push_transaction(tx)

        print(f" ==== test_tx_propagation O")
        await time_out_assert(
            10,
            full_node_api_0.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        print(f" ==== test_tx_propagation P")
        await time_out_assert(
            10,
            full_node_api_1.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        print(f" ==== test_tx_propagation Q")
        await time_out_assert(
            10,
            full_node_api_2.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )

        # Farm another block
        print(f" ==== test_tx_propagation R")
        for i in range(1, 8):
            print(f" ==== test_tx_propagation R {i}")
            await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(token_bytes()))
        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )
        print(f"Funds: {funds}")
        print(f" ==== test_tx_propagation S")
        await time_out_assert(
            10,
            wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance,
            (funds - 10),
        )
        print(f" ==== test_tx_propagation T")
        await time_out_assert(15, wallet_1.wallet_state_manager.main_wallet.get_confirmed_balance, 10)
        print(f" ==== test_tx_propagation U")

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

        print(f" ==== test_mempool_tx_sync: A")
        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()

        # wallet0 <-> sever0 <-> server1

        print(f" ==== test_mempool_tx_sync: B")
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)
        print(f" ==== test_mempool_tx_sync: C")
        await server_0.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        print(f" ==== test_mempool_tx_sync: D")
        for i in range(num_blocks):
            print(f" ==== test_mempool_tx_sync: D {i}")
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        print(f" ==== test_mempool_tx_sync: E")
        all_blocks = await full_node_api_0.get_all_full_blocks()

        print(f" ==== test_mempool_tx_sync: F")
        for block in all_blocks:
            print(f" ==== test_mempool_tx_sync: F {block}")
            await full_node_api_2.full_node.respond_block(full_node_protocol.RespondBlock(block))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        print(f" ==== test_mempool_tx_sync: G")
        await time_out_assert(10, wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance, funds)

        print(f" ==== test_mempool_tx_sync: H")
        tx = await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(10, token_bytes(), 0)
        print(f" ==== test_mempool_tx_sync: I")
        await wallet_0.wallet_state_manager.main_wallet.push_transaction(tx)

        print(f" ==== test_mempool_tx_sync: J")
        await time_out_assert(
            10,
            full_node_api_0.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        print(f" ==== test_mempool_tx_sync: K")
        await time_out_assert(
            10,
            full_node_api_1.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        print(f" ==== test_mempool_tx_sync: L")
        await time_out_assert(
            10,
            full_node_api_2.full_node.mempool_manager.get_spendbundle,
            None,
            tx.name,
        )

        # make a final connection.
        # wallet0 <-> sever0 <-> server1 <-> server2

        print(f" ==== test_mempool_tx_sync: M")
        await server_1.start_client(PeerInfo(self_hostname, uint16(server_2._port)), None)

        print(f" ==== test_mempool_tx_sync: N")
        await time_out_assert(
            10,
            full_node_api_0.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        print(f" ==== test_mempool_tx_sync: O")
        await time_out_assert(
            10,
            full_node_api_1.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        print(f" ==== test_mempool_tx_sync: P")
        await time_out_assert(
            10,
            full_node_api_2.full_node.mempool_manager.get_spendbundle,
            tx.spend_bundle,
            tx.name,
        )
        print(f" ==== test_mempool_tx_sync: Q")
