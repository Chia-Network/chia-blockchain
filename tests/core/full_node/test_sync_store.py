import asyncio

import pytest
from src.full_node.sync_store import SyncStore
from src.util.hash import std_hash


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestStore:
    @pytest.mark.asyncio
    async def test_basic_store(self):
        store = await SyncStore.create()
        await SyncStore.create()

        # Save/get sync
        for sync_mode in (False, True):
            store.set_sync_mode(sync_mode)
            assert sync_mode == store.get_sync_mode()

        # clear sync info
        await store.clear_sync_info()

        store.set_peak_target(std_hash(b"1"), 100)
        assert store.get_sync_target_hash() == std_hash(b"1")
        assert store.get_sync_target_height() == 100

        peer_ids = [std_hash(bytes([a])) for a in range(3)]

        assert store.get_peers_that_have_peak([]) == set()
        assert store.get_peers_that_have_peak([std_hash(b"block1")]) == set()

        assert store.get_heaviest_peak() is None
        assert len(store.get_peak_of_each_peer()) == 0
        store.peer_has_block(std_hash(b"block10"), peer_ids[0], 500, 10, True)
        store.peer_has_block(std_hash(b"block1"), peer_ids[0], 300, 1, False)
        store.peer_has_block(std_hash(b"block1"), peer_ids[1], 300, 1, True)
        store.peer_has_block(std_hash(b"block10"), peer_ids[2], 500, 10, False)
        store.peer_has_block(std_hash(b"block1"), peer_ids[2], 300, 1, False)

        assert store.get_heaviest_peak()[0] == std_hash(b"block10")
        assert store.get_heaviest_peak()[1] == 10
        assert store.get_heaviest_peak()[2] == 500

        assert len(store.get_peak_of_each_peer()) == 2
        store.peer_has_block(std_hash(b"block1"), peer_ids[2], 500, 1, True)
        assert len(store.get_peak_of_each_peer()) == 3
        assert store.get_peak_of_each_peer()[peer_ids[0]][2] == 500
        assert store.get_peak_of_each_peer()[peer_ids[1]][2] == 300
        assert store.get_peak_of_each_peer()[peer_ids[2]][2] == 500

        assert store.get_peers_that_have_peak([std_hash(b"block1")]) == set(peer_ids)
        assert store.get_peers_that_have_peak([std_hash(b"block10")]) == {peer_ids[0], peer_ids[2]}

        store.peer_disconnected(peer_ids[0])
        assert store.get_heaviest_peak()[2] == 500
        assert len(store.get_peak_of_each_peer()) == 2
        assert store.get_peers_that_have_peak([std_hash(b"block10")]) == {peer_ids[2]}
        store.peer_disconnected(peer_ids[2])
        assert store.get_heaviest_peak()[2] == 300
        store.peer_has_block(std_hash(b"block30"), peer_ids[0], 700, 30, True)
        assert store.get_peak_of_each_peer()[peer_ids[0]][2] == 700
        assert store.get_heaviest_peak()[2] == 700
