import asyncio
from typing import List

import pytest
from blspy import ExtendedPrivateKey
from chiabip158 import PyBIP158

from src.wallet.wallet_node import WalletNode
from tests.setup_nodes import (
    setup_two_nodes,
    test_constants,
    bt,
    setup_node_simulator_and_wallet,
)
from src.util.config import load_config


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestFilter:
    @pytest.fixture(scope="function")
    async def wallet_and_node(self):
        async for _ in setup_node_simulator_and_wallet():
            yield _

    @pytest.mark.asyncio
    async def test_basic_filter_test(self, wallet_and_node):
        sk = bytes(ExtendedPrivateKey.from_seed(b"")).hex()
        config = load_config("config.yaml", "wallet")
        key_config = {"wallet_sk": sk}
        full_node_1, wallet_node, server_1, server_2 = wallet_and_node
        wallet = wallet_node.main_wallet

        num_blocks = 2
        ph = await wallet.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            test_constants, num_blocks, [], 10, reward_puzzlehash=ph,
        )

        for i in range(1, num_blocks):
            byte_array_tx: List[bytes] = []
            block = blocks[i]
            coinbase = bytearray(block.header.data.coinbase.puzzle_hash)
            fee = bytearray(block.header.data.fees_coin.puzzle_hash)
            byte_array_tx.append(coinbase)
            byte_array_tx.append(fee)

            pl = PyBIP158(byte_array_tx)
            present = pl.Match(coinbase)
            fee_present = pl.Match(fee)

            assert present
            assert fee_present
