import asyncio
from secrets import token_bytes
from pathlib import Path
from typing import Any, Dict
import sqlite3
import random

import aiosqlite
import pytest
from src.full_node.sync_store import SyncStore
from src.full_node.blockchain import Blockchain
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from tests.block_tools import BlockTools

bt = BlockTools()

test_constants: Dict[str, Any] = {
    "DIFFICULTY_STARTING": 5,
    "DISCRIMINANT_SIZE_BITS": 16,
    "BLOCK_TIME_TARGET": 10,
    "MIN_BLOCK_TIME": 2,
    "MIN_ITERS_STARTING": 100,
    "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
    "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
}
test_constants["GENESIS_BLOCK"] = bytes(
    bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")
)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestStore:
    @pytest.mark.asyncio
    async def test_basic_store(self):
        assert sqlite3.threadsafety == 1
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")
        blocks_alt = bt.get_consecutive_blocks(test_constants, 3, [], 9, b"1")
        db = await SyncStore.create()
        db_2 = await SyncStore.create()

        # Save/get sync
        for sync_mode in (False, True):
            db.set_sync_mode(sync_mode)
            assert sync_mode == db.get_sync_mode()
        genesis = FullBlock.from_bytes(test_constants["GENESIS_BLOCK"])

        # clear sync info
        await db.clear_sync_info()

        # add/get potential tip, get potential tips num
        db.add_potential_tip(blocks[6])
        assert blocks[6] == db.get_potential_tip(blocks[6].header_hash)
