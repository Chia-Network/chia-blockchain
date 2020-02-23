import asyncio
from typing import List

import pytest
from blspy import ExtendedPrivateKey
from chiabip158 import PyBIP158

from src.wallet.wallet import Wallet
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

        wallet = await Wallet.create({}, key_config)
        await wallet.wallet_store._clear_database()

        num_blocks = 2
        blocks = bt.get_consecutive_blocks(
            test_constants,
            num_blocks,
            [],
            10,
            reward_puzzlehash=wallet.get_new_puzzlehash(),
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

        await wallet.wallet_store.close()
