import asyncio
from typing import List

import pytest
from blspy import ExtendedPrivateKey
from chiabip158 import PyBIP158

from src.wallet.wallet_node import WalletNode
from tests.setup_nodes import setup_two_nodes, test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestFilter:
    @pytest.fixture(scope="function")
    async def two_nodes(self):
        async for _ in setup_two_nodes({"COINBASE_FREEZE_PERIOD": 0}):
            yield _

    @pytest.mark.asyncio
    async def test_basic_filter_test(self, two_nodes):
        sk = bytes(ExtendedPrivateKey.from_seed(b"")).hex()
        key_config = {"wallet_sk": sk}
        wallet_node = await WalletNode.create({}, key_config)
        wallet = wallet_node.wallet
        await wallet_node.wallet_store._clear_database()

        num_blocks = 2
        ph = await wallet.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            test_constants,
            num_blocks,
            [],
            10,
            reward_puzzlehash=ph,
        )

        for i in range(1, num_blocks):
            byte_array_tx: List[bytes] = []
            block = blocks[i]
            coinbase = bytearray(block.body.coinbase.puzzle_hash)
            fee = bytearray(block.body.fees_coin.puzzle_hash)
            byte_array_tx.append(coinbase)
            byte_array_tx.append(fee)

            pl = PyBIP158(byte_array_tx)
            present = pl.Match(coinbase)
            fee_present = pl.Match(fee)

            assert present
            assert fee_present

        await wallet_node.wallet_store.close()
        await wallet_node.tx_store.close()
