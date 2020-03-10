import asyncio
from secrets import token_bytes

import pytest

from src.types.header import Header
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32
from tests.setup_nodes import (
    setup_node_simulator_and_two_wallets,
    setup_node_simulator_and_wallet,
)
from src.consensus.block_rewards import calculate_base_fee, calculate_block_reward


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletSimulator:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_node_simulator_and_wallet():
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_node_simulator_and_two_wallets(
            {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    @pytest.mark.asyncio
    async def test_wallet_coinbase(self, wallet_node):
        num_blocks = 10
        full_node_1, wallet_node, server_1, server_2 = wallet_node
        wallet = wallet_node.wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(ph)

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
        (
            full_node_1,
            wallet_node,
            wallet_node_2,
            server_1,
            server_2,
            server_3,
        ) = two_wallet_nodes
        wallet = wallet_node.wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )

        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(ph)

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(0, num_blocks - 2)
            ]
        )

        await asyncio.sleep(2)

        assert await wallet.get_confirmed_balance() == funds
        assert await wallet.get_unconfirmed_balance() == funds

        spend_bundle = await wallet.generate_signed_transaction(
            10, await wallet_node_2.wallet.get_new_puzzlehash(), 0
        )
        await wallet.push_transaction(spend_bundle)

        await asyncio.sleep(2)
        confirmed_balance = await wallet.get_confirmed_balance()
        unconfirmed_balance = await wallet.get_unconfirmed_balance()

        assert confirmed_balance == funds
        assert unconfirmed_balance == funds - 10

        for i in range(0, num_blocks):
            await full_node_1.farm_new_block(ph)

        await asyncio.sleep(2)

        new_funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(0, (2 * num_blocks) - 2)
            ]
        )

        confirmed_balance = await wallet.get_confirmed_balance()
        unconfirmed_balance = await wallet.get_unconfirmed_balance()

        assert confirmed_balance == new_funds - 10
        assert unconfirmed_balance == new_funds - 10

    @pytest.mark.asyncio
    async def test_wallet_coinbase_reorg(self, wallet_node):
        num_blocks = 10
        full_node_1, wallet_node, server_1, server_2 = wallet_node
        wallet = wallet_node.wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )
        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(ph)

        await asyncio.sleep(3)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )
        assert await wallet.get_confirmed_balance() == funds

        await full_node_1.reorg_from_index_to_new_index(
            5, num_blocks + 3, token_bytes()
        )
        await asyncio.sleep(3)

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, 4)
            ]
        )

        assert await wallet.get_confirmed_balance() == funds
