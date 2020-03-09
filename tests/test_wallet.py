import asyncio

import pytest
from src.protocols import full_node_protocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32
from tests.setup_nodes import (
    setup_node_and_wallet,
    setup_node_and_two_wallets,
    test_constants,
    bt,
)
from src.util.bundle_tools import best_solution_program
from src.consensus.block_rewards import calculate_base_fee, calculate_block_reward


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWallet:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_node_and_wallet():
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_node_and_two_wallets({"COINBASE_FREEZE_PERIOD": 0}):
            yield _

    @pytest.mark.asyncio
    async def test_wallet_coinbase(self, wallet_node):
        num_blocks = 10
        full_node_1, wallet_node, server_1, server_2 = wallet_node
        wallet = wallet_node.wallet
        ph = await wallet.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, reward_puzzlehash=ph,
        )
        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )
        for i in range(1, len(blocks)):
            async for msg in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                server_1.push_message(msg)
        await asyncio.sleep(3)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, num_blocks - 1)
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
        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, reward_puzzlehash=ph,
        )
        await server_2.start_client(
            PeerInfo(server_1._host, uint16(server_1._port)), None
        )
        for i in range(1, len(blocks)):
            async for msg in full_node_1.respond_block(
                full_node_protocol.RespondBlock(blocks[i])
            ):
                server_1.push_message(msg)
        await asyncio.sleep(2)
        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, len(blocks) - 2)
            ]
        )
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

        program = best_solution_program(spend_bundle)

        dic_h = {11: (program, spend_bundle.aggregated_signature)}
        more_blocks = bt.get_consecutive_blocks(
            test_constants,
            num_blocks,
            blocks,
            10,
            reward_puzzlehash=ph,
            transaction_data_at_height=dic_h,
        )
        for i in range(1, len(more_blocks)):
            async for msg in full_node_1.respond_block(
                full_node_protocol.RespondBlock(more_blocks[i])
            ):
                server_1.push_message(msg)
        await asyncio.sleep(2)
        new_funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, len(more_blocks) - 2)
            ]
        )
        confirmed_balance = await wallet.get_confirmed_balance()
        unconfirmed_balance = await wallet.get_unconfirmed_balance()

        # TODO(straya): fix test
        assert confirmed_balance == new_funds - 10
        assert unconfirmed_balance == new_funds - 10
