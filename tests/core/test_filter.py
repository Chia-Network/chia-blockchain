import asyncio
from typing import List

import pytest
from chiabip158 import PyBIP158

from tests.setup_nodes import setup_simulators_and_wallets, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestFilter:
    @pytest.fixture(scope="function")
    async def wallet_and_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.mark.asyncio
    async def test_basic_filter_test(self, wallet_and_node):
        full_nodes, wallets = wallet_and_node
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        num_blocks = 2
        ph = await wallet.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            10,
            guarantee_transaction_block=True,
            farmer_reward_puzzle_hash=ph,
            pool_reward_puzzle_hash=ph,
        )
        for i in range(1, num_blocks):
            byte_array_tx: List[bytes] = []
            block = blocks[i]
            coins = list(block.get_included_reward_coins())
            coin_0 = bytearray(coins[0].puzzle_hash)
            coin_1 = bytearray(coins[1].puzzle_hash)
            byte_array_tx.append(coin_0)
            byte_array_tx.append(coin_1)

            pl = PyBIP158(byte_array_tx)
            present = pl.Match(coin_0)
            fee_present = pl.Match(coin_1)

            assert present
            assert fee_present
