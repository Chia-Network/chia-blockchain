from __future__ import annotations

import asyncio
import random
from typing import Optional

import pytest

from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.full_node_api import FullNodeAPI
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint32
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG


class TestTransactions:
    @pytest.mark.anyio
    async def test_wallet_coinbase(self, simulator_and_wallet, self_hostname):
        num_blocks = 5
        full_nodes, wallets, _ = simulator_and_wallet
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
        for i in range(num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)
        )
        # funds += calculate_base_farmer_reward(0)
        await asyncio.sleep(2)
        print(await wallet.get_confirmed_balance(), funds)
        await time_out_assert(20, wallet.get_confirmed_balance, funds)

    @pytest.mark.anyio
    async def test_tx_propagation(self, three_nodes_two_wallets, self_hostname, seeded_random: random.Random):
        num_blocks = 5
        full_nodes, wallets, _ = three_nodes_two_wallets

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
        await wallet_server_0.start_client(PeerInfo(self_hostname, server_0.get_port()), None)
        await server_0.start_client(PeerInfo(self_hostname, server_1.get_port()), None)
        await server_1.start_client(PeerInfo(self_hostname, server_2.get_port()), None)
        await wallet_server_1.start_client(PeerInfo(self_hostname, server_2.get_port()), None)

        for i in range(num_blocks):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)
        )
        await time_out_assert(20, wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance, funds)

        async def peak_height(fna: FullNodeAPI):
            peak: Optional[BlockRecord] = fna.full_node.blockchain.get_peak()
            if peak is None:
                return -1
            peak_height = peak.height
            return peak_height

        await time_out_assert(20, peak_height, num_blocks, full_node_api_1)
        await time_out_assert(20, peak_height, num_blocks, full_node_api_2)

        async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(10, ph1, action_scope, 0)
        [tx] = action_scope.side_effects.transactions

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
            await full_node_api_1.farm_new_transaction_block(FarmNewBlockProtocol(bytes32.random(seeded_random)))
        funds = sum(
            calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks + 1)
        )
        print(f"Funds: {funds}")
        await time_out_assert(
            10,
            wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance,
            (funds - 10),
        )
        await time_out_assert(20, wallet_1.wallet_state_manager.main_wallet.get_confirmed_balance, 10)

    @pytest.mark.anyio
    async def test_mempool_tx_sync(self, three_nodes_two_wallets, self_hostname, seeded_random: random.Random):
        num_blocks = 5
        full_nodes, wallets, _ = three_nodes_two_wallets

        wallet_0, wallet_server_0 = wallets[0]
        full_node_api_0 = full_nodes[0]
        server_0 = full_node_api_0.server
        full_node_api_1 = full_nodes[1]
        server_1 = full_node_api_1.server
        full_node_api_2 = full_nodes[2]
        server_2 = full_node_api_2.server

        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()

        # wallet0 <-> sever0 <-> server1

        await wallet_server_0.start_client(PeerInfo(self_hostname, server_0.get_port()), None)
        await server_0.start_client(PeerInfo(self_hostname, server_1.get_port()), None)

        for i in range(num_blocks):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        all_blocks = await full_node_api_0.get_all_full_blocks()

        for block in all_blocks:
            await full_node_api_2.full_node.add_block(block)

        funds = sum(
            calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)
        )
        await time_out_assert(20, wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance, funds)

        async with wallet_0.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(
                10, bytes32.random(seeded_random), action_scope, 0
            )
        [tx] = action_scope.side_effects.transactions

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

        await server_1.start_client(PeerInfo(self_hostname, server_2.get_port()), None)

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
