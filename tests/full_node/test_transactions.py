import asyncio
from secrets import token_bytes

import pytest

from src.protocols import full_node_protocol
from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32
from tests.setup_nodes import setup_simulators_and_wallets
from src.consensus.block_rewards import calculate_base_fee, calculate_block_reward


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
        async for _ in setup_simulators_and_wallets(
            1, 2, {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    @pytest.fixture(scope="function")
    async def three_nodes_two_wallets(self):
        async for _ in setup_simulators_and_wallets(
            3, 2, {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    @pytest.mark.asyncio
    async def test_wallet_coinbase(self, wallet_node):
        num_blocks = 10
        full_nodes, wallets = wallet_node
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(3)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )
        assert await wallet.get_confirmed_balance() == funds

    @pytest.mark.asyncio
    async def test_tx_propagation(self, three_nodes_two_wallets):
        num_blocks = 10
        full_nodes, wallets = three_nodes_two_wallets

        wallet_0, wallet_server_0 = wallets[0]
        wallet_1, wallet_server_1 = wallets[1]
        full_node_0, server_0 = full_nodes[0]
        full_node_1, server_1 = full_nodes[1]
        full_node_2, server_2 = full_nodes[2]

        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()
        ph1 = await wallet_1.wallet_state_manager.main_wallet.get_new_puzzlehash()

        #
        # wallet0 <-> sever0 <-> server1 <-> server2 <-> wallet1
        #
        await wallet_server_0.start_client(
            PeerInfo("localhost", uint16(server_0._port)), None
        )
        await server_0.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_1.start_client(PeerInfo("localhost", uint16(server_2._port)), None)
        await wallet_server_1.start_client(
            PeerInfo("localhost", uint16(server_2._port)), None
        )

        for i in range(1, num_blocks):
            await full_node_0.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(3)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )
        assert (
            await wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance()
            == funds
        )

        tx = await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(
            10, ph1, 0
        )
        await wallet_0.wallet_state_manager.main_wallet.push_transaction(tx)

        await asyncio.sleep(3)

        bundle0 = full_node_0.mempool_manager.get_spendbundle(tx.name())
        bundle1 = full_node_1.mempool_manager.get_spendbundle(tx.name())
        bundle2 = full_node_2.mempool_manager.get_spendbundle(tx.name())

        assert tx.spend_bundle == bundle0
        assert tx.spend_bundle == bundle1
        assert tx.spend_bundle == bundle2

        # Farm another block
        for i in range(1, 8):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        await asyncio.sleep(2)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks)
            ]
        )

        assert (
            await wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance()
            == funds - 10
        )
        assert (
            await wallet_1.wallet_state_manager.main_wallet.get_confirmed_balance()
            == 10
        )

    @pytest.mark.asyncio
    async def test_mempool_tx_sync(self, three_nodes_two_wallets):
        num_blocks = 10
        full_nodes, wallets = three_nodes_two_wallets

        wallet_0, wallet_server_0 = wallets[0]
        full_node_0, server_0 = full_nodes[0]
        full_node_1, server_1 = full_nodes[1]
        full_node_2, server_2 = full_nodes[2]

        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()

        # wallet0 <-> sever0 <-> server1

        await wallet_server_0.start_client(
            PeerInfo("localhost", uint16(server_0._port)), None
        )
        await server_0.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, num_blocks):
            await full_node_0.farm_new_block(FarmNewBlockProtocol(ph))

        all_blocks = await full_node_0.get_current_blocks(full_node_0.get_tip())

        for block in all_blocks:
            async for _ in full_node_2.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass

        await asyncio.sleep(2)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )
        assert (
            await wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance()
            == funds
        )

        tx = await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(
            10, token_bytes(), 0
        )
        await wallet_0.wallet_state_manager.main_wallet.push_transaction(tx)

        await asyncio.sleep(2)

        bundle0 = full_node_0.mempool_manager.get_spendbundle(tx.name())
        bundle1 = full_node_1.mempool_manager.get_spendbundle(tx.name())
        bundle2 = full_node_2.mempool_manager.get_spendbundle(tx.name())

        assert tx.spend_bundle == bundle0
        assert tx.spend_bundle == bundle1
        assert None is bundle2

        # make a final connection.
        # wallet0 <-> sever0 <-> server1 <-> server2

        await server_1.start_client(PeerInfo("localhost", uint16(server_2._port)), None)

        await asyncio.sleep(2)

        bundle0 = full_node_0.mempool_manager.get_spendbundle(tx.name())
        bundle1 = full_node_1.mempool_manager.get_spendbundle(tx.name())
        bundle2 = full_node_2.mempool_manager.get_spendbundle(tx.name())

        assert tx.spend_bundle == bundle0
        assert tx.spend_bundle == bundle1
        assert tx.spend_bundle == bundle2
