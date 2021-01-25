import asyncio
import sqlite3

import pytest
from src.full_node.sync_store import SyncStore


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestStore:
    @pytest.mark.asyncio
    async def test_basic_store(self):
        assert sqlite3.threadsafety == 1
        db = await SyncStore.create()
        await SyncStore.create()

        # Save/get sync
        for sync_mode in (False, True):
            db.set_sync_mode(sync_mode)
            assert sync_mode == db.get_sync_mode()

        # clear sync info
        await db.clear_sync_info()
