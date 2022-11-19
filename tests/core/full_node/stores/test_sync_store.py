from __future__ import annotations

import pytest

from chia.full_node.sync_store import SyncStore
from chia.util.hash import std_hash


class TestStore:
    @pytest.mark.asyncio
    async def test_basic_store(self):
        store = SyncStore()

        # Save/get sync
        for sync_mode in (False, True):
            store.set_sync_mode(sync_mode)
            assert sync_mode == store.get_sync_mode()

        # clear sync info
        await store.clear_sync_info()

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

        assert store.get_heaviest_peak().header_hash == std_hash(b"block10")
        assert store.get_heaviest_peak().height == 10
        assert store.get_heaviest_peak().weight == 500

        assert len(store.get_peak_of_each_peer()) == 2
        store.peer_has_block(std_hash(b"block1"), peer_ids[2], 500, 1, True)
        assert len(store.get_peak_of_each_peer()) == 3
        assert store.get_peak_of_each_peer()[peer_ids[0]].weight == 500
        assert store.get_peak_of_each_peer()[peer_ids[1]].weight == 300
        assert store.get_peak_of_each_peer()[peer_ids[2]].weight == 500

        assert store.get_peers_that_have_peak([std_hash(b"block1")]) == set(peer_ids)
        assert store.get_peers_that_have_peak([std_hash(b"block10")]) == {peer_ids[0], peer_ids[2]}

        store.peer_disconnected(peer_ids[0])
        assert store.get_heaviest_peak().weight == 500
        assert len(store.get_peak_of_each_peer()) == 2
        assert store.get_peers_that_have_peak([std_hash(b"block10")]) == {peer_ids[2]}
        store.peer_disconnected(peer_ids[2])
        assert store.get_heaviest_peak().weight == 300
        store.peer_has_block(std_hash(b"block30"), peer_ids[0], 700, 30, True)
        assert store.get_peak_of_each_peer()[peer_ids[0]].weight == 700
        assert store.get_heaviest_peak().weight == 700
