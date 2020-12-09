# import asyncio
# from typing import List
#
# import pytest
# from chiabip158 import PyBIP158
#
# from tests.setup_nodes import test_constants, setup_simulators_and_wallets, bt
#
#
# @pytest.fixture(scope="module")
# def event_loop():
#     loop = asyncio.get_event_loop()
#     yield loop
#
#
# class TestFilter:
#     @pytest.fixture(scope="function")
#     async def wallet_and_node(self):
#         async for _ in setup_simulators_and_wallets(1, 1, {}):
#             yield _
#
#     @pytest.mark.asyncio
#     async def test_basic_filter_test(self, wallet_and_node):
#         full_nodes, wallets = wallet_and_node
#         wallet_node, server_2 = wallets[0]
#         wallet = wallet_node.wallet_state_manager.main_wallet
#
#         num_blocks = 2
#         await wallet.get_new_puzzlehash()
#         blocks = bt.get_consecutive_blocks(test_constants, num_blocks, [], 10)
#
#         for i in range(1, num_blocks):
#             byte_array_tx: List[bytes] = []
#             block = blocks[i]
#             coinbase = bytearray(block.get_coinbase().puzzle_hash)
#             fee = bytearray(block.get_fees_coin().puzzle_hash)
#             byte_array_tx.append(coinbase)
#             byte_array_tx.append(fee)
#
#             pl = PyBIP158(byte_array_tx)
#             present = pl.Match(coinbase)
#             fee_present = pl.Match(fee)
#
#             assert present
#             assert fee_present
