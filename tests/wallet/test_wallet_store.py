# import asyncio
# from secrets import token_bytes
# from pathlib import Path
# from typing import Any, Dict
# import sqlite3
# import random

# import pytest
# from src.full_node.store import FullNodeStore
# from src.types.full_block import FullBlock
# from src.types.sized_bytes import bytes32
# from src.util.ints import uint32, uint64
# from tests.block_tools import BlockTools

# bt = BlockTools()

# test_constants: Dict[str, Any] = {
#     "DIFFICULTY_STARTING": 5,
#     "DISCRIMINANT_SIZE_BITS": 16,
#     "BLOCK_TIME_TARGET": 10,
#     "MIN_BLOCK_TIME": 2,
#     "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
#     "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
# }
# test_constants["GENESIS_BLOCK"] = bytes(
#     bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
# )


# @pytest.fixture(scope="module")
# def event_loop():
#     loop = asyncio.get_event_loop()
#     yield loop


# class TestWalletStore:
#     @pytest.mark.asyncio
#     async def test_store(self):
#         blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")
#         db_filename = Path("blockchain_wallet_store_test.db")

#         if db_filename.exists():
#             db_filename.unlink()

#         db = await FullNodeStore.create(db_filename)
#         try:
#             await db._clear_database()
