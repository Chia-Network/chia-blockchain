import asyncio
from secrets import token_bytes

import pytest

from src.protocols import full_node_protocol
from src.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32
from tests.setup_nodes import setup_simulators_and_wallets
from src.consensus.block_rewards import calculate_base_fee, calculate_block_reward


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
    async def test_wallet_make_transaction(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await asyncio.sleep(2)

        assert await wallet.get_confirmed_balance() == funds
        assert await wallet.get_unconfirmed_balance() == funds

        tx = await wallet.generate_signed_transaction(
            10,
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            0,
        )
        await wallet.push_transaction(tx)

        await asyncio.sleep(2)
        confirmed_balance = await wallet.get_confirmed_balance()
        unconfirmed_balance = await wallet.get_unconfirmed_balance()

        assert confirmed_balance == funds
        assert unconfirmed_balance == funds - 10

        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(2)

        new_funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, (2 * num_blocks) - 1)
            ]
        )

        confirmed_balance = await wallet.get_confirmed_balance()
        unconfirmed_balance = await wallet.get_unconfirmed_balance()

        assert confirmed_balance == new_funds - 10
        assert unconfirmed_balance == new_funds - 10

    @pytest.mark.asyncio
    async def test_wallet_coinbase_reorg(self, wallet_node):
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

        await full_node_1.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(5), uint32(num_blocks + 3), token_bytes())
        )
        await asyncio.sleep(3)

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, 5)
            ]
        )

        assert await wallet.get_confirmed_balance() == funds

    @pytest.mark.asyncio
    async def test_wallet_send_to_three_peers(self, three_sim_two_wallets):
        num_blocks = 10
        full_nodes, wallets = three_sim_two_wallets

        wallet_0, wallet_server_0 = wallets[0]
        full_node_0, server_0 = full_nodes[0]
        full_node_1, server_1 = full_nodes[1]
        full_node_2, server_2 = full_nodes[2]

        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()

        # wallet0 <-> sever0
        await wallet_server_0.start_client(
            PeerInfo("localhost", uint16(server_0._port)), None
        )

        for i in range(1, num_blocks):
            await full_node_0.farm_new_block(FarmNewBlockProtocol(ph))

        all_blocks = await full_node_0.get_current_blocks(full_node_0.get_tip())

        for block in all_blocks:
            async for _ in full_node_1.respond_block(
                full_node_protocol.RespondBlock(block)
            ):
                pass
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

        await asyncio.sleep(1)

        bundle0 = full_node_0.mempool_manager.get_spendbundle(tx.name())
        assert bundle0 is not None

        # wallet0 <-> sever1
        await wallet_server_0.start_client(
            PeerInfo("localhost", uint16(server_1._port)), wallet_0._on_connect
        )
        await asyncio.sleep(1)

        bundle1 = full_node_1.mempool_manager.get_spendbundle(tx.name())
        assert bundle1 is not None

        # wallet0 <-> sever2
        await wallet_server_0.start_client(
            PeerInfo("localhost", uint16(server_2._port)), wallet_0._on_connect
        )
        await asyncio.sleep(1)

        bundle2 = full_node_2.mempool_manager.get_spendbundle(tx.name())
        assert bundle2 is not None

    @pytest.mark.asyncio
    async def test_wallet_make_transaction_hop(self, two_wallet_nodes_five_freeze):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes_five_freeze
        full_node_0, full_node_server = full_nodes[0]
        wallet_node_0, wallet_0_server = wallets[0]
        wallet_node_1, wallet_1_server = wallets[1]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        ph = await wallet_0.get_new_puzzlehash()

        await wallet_0_server.start_client(
            PeerInfo("localhost", uint16(full_node_server._port)), None
        )

        await wallet_1_server.start_client(
            PeerInfo("localhost", uint16(full_node_server._port)), None
        )

        for i in range(0, num_blocks):
            await full_node_0.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await asyncio.sleep(2)

        assert await wallet_0.get_confirmed_balance() == funds
        assert await wallet_0.get_unconfirmed_balance() == funds

        tx = await wallet_0.generate_signed_transaction(
            10,
            await wallet_node_1.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            0,
        )

        await wallet_0.push_transaction(tx)

        await asyncio.sleep(1)
        # Full node height 11, wallet height 9
        confirmed_balance = await wallet_0.get_confirmed_balance()
        unconfirmed_balance = await wallet_0.get_unconfirmed_balance()

        assert confirmed_balance == funds
        assert unconfirmed_balance == funds - 10

        for i in range(0, 7):
            await full_node_0.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        await asyncio.sleep(1)

        new_funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        # Full node height 17, wallet height 15
        confirmed_balance = await wallet_0.get_confirmed_balance()
        unconfirmed_balance = await wallet_0.get_unconfirmed_balance()
        wallet_2_confirmed_balance = await wallet_1.get_confirmed_balance()

        assert confirmed_balance == new_funds - 10
        assert unconfirmed_balance == new_funds - 10
        assert wallet_2_confirmed_balance == 10

        tx = await wallet_1.generate_signed_transaction(
            5, await wallet_0.get_new_puzzlehash(), 0
        )
        await wallet_1.push_transaction(tx)

        for i in range(0, 7):
            await full_node_0.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        await asyncio.sleep(1)

        confirmed_balance = await wallet_0.get_confirmed_balance()
        unconfirmed_balance = await wallet_0.get_unconfirmed_balance()
        wallet_2_confirmed_balance = await wallet_1.get_confirmed_balance()

        assert confirmed_balance == new_funds - 5
        assert unconfirmed_balance == new_funds - 5
        assert wallet_2_confirmed_balance == 5

    @pytest.mark.asyncio
    async def test_wallet_make_transaction_with_fee(self, two_wallet_nodes):
        num_blocks = 10
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await asyncio.sleep(2)

        assert await wallet.get_confirmed_balance() == funds
        assert await wallet.get_unconfirmed_balance() == funds
        tx_amount = 32000000000000
        tx_fee = 10
        tx = await wallet.generate_signed_transaction(
            tx_amount,
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            tx_fee,
        )

        fees = tx.spend_bundle.fees()
        assert fees == tx_fee

        await wallet.push_transaction(tx)

        await asyncio.sleep(2)
        confirmed_balance = await wallet.get_confirmed_balance()
        unconfirmed_balance = await wallet.get_unconfirmed_balance()

        assert confirmed_balance == funds
        assert unconfirmed_balance == funds - tx_amount - tx_fee

        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(token_bytes()))

        await asyncio.sleep(2)

        new_funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        confirmed_balance = await wallet.get_confirmed_balance()
        unconfirmed_balance = await wallet.get_unconfirmed_balance()

        assert confirmed_balance == new_funds - tx_amount - tx_fee
        assert unconfirmed_balance == new_funds - tx_amount - tx_fee
