import asyncio
import sqlite3

import pytest
from src.full_node.sync_store import SyncStore
from src.types.full_block import FullBlock
from tests.setup_nodes import test_constants, bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestStore:
    @pytest.mark.asyncio
    async def test_basic_store(self):
        assert sqlite3.threadsafety == 1
        blocks = bt.get_consecutive_blocks(test_constants, 9, [], 9, b"0")
        # blocks_alt = bt.get_consecutive_blocks(test_constants, 3, [], 9, b"1")
        bt.get_consecutive_blocks(test_constants, 3, [], 9, b"1")
        db = await SyncStore.create()
        # db_2 = await SyncStore.create()
        await SyncStore.create()

        # Save/get sync
        for sync_mode in (False, True):
            db.set_sync_mode(sync_mode)
            assert sync_mode == db.get_sync_mode()
        FullBlock.from_bytes(test_constants.GENESIS_BLOCK)

        # clear sync info
        await db.clear_sync_info()

        # add/get potential tip, get potential tips num
        db.add_potential_tip(blocks[6])
        assert blocks[6] == db.get_potential_tip(blocks[6].header_hash)
