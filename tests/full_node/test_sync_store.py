import asyncio
import sqlite3

import pytest
from src.full_node.sync_store import SyncStore
from tests.setup_nodes import bt


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestStore:
    @pytest.mark.asyncio
    async def test_basic_store(self):
        assert sqlite3.threadsafety == 1
        blocks = bt.get_consecutive_blocks(2)
        db = await SyncStore.create()
        await SyncStore.create()

        # Save/get sync
        for sync_mode in (False, True):
            db.set_sync_mode(sync_mode)
            assert sync_mode == db.get_sync_mode()

        # clear sync info
        await db.clear_sync_info()

        # add/get potential tip, get potential tips num
        db.add_potential_peak(blocks[1].header_hash, blocks[1].sub_block_height, blocks[1].weight)
        potential_peak = db.get_potential_peak(blocks[1].header_hash)
        assert blocks[1].sub_block_height == potential_peak[0]
        assert blocks[1].weight == potential_peak[1]
