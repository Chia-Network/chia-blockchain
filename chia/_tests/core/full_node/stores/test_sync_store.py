from __future__ import annotations

import random

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint128

from chia.full_node.sync_store import SyncStore
from chia.util.hash import std_hash


@pytest.mark.anyio
async def test_basic_store() -> None:
    store = SyncStore()

    # Save/get sync
    for sync_mode in (False, True):
        store.set_sync_mode(sync_mode)
        assert sync_mode == store.get_sync_mode()

    peer_ids = [std_hash(bytes([a])) for a in range(3)]

    assert store.get_peers_that_have_peak([]) == set()
    assert store.get_peers_that_have_peak([std_hash(b"block1")]) == set()

    assert store.get_heaviest_peak() is None
    assert len(store.get_peak_of_each_peer()) == 0
    store.peer_has_block(std_hash(b"block10"), peer_ids[0], uint128(500), uint32(10), True)
    store.peer_has_block(std_hash(b"block1"), peer_ids[0], uint128(300), uint32(1), False)
    store.peer_has_block(std_hash(b"block1"), peer_ids[1], uint128(300), uint32(1), True)
    store.peer_has_block(std_hash(b"block10"), peer_ids[2], uint128(500), uint32(10), False)
    store.peer_has_block(std_hash(b"block1"), peer_ids[2], uint128(300), uint32(1), False)

    peak = store.get_heaviest_peak()
    assert peak is not None
    assert peak.header_hash == std_hash(b"block10")
    assert peak.height == 10
    assert peak.weight == 500

    assert len(store.get_peak_of_each_peer()) == 2
    store.peer_has_block(std_hash(b"block1"), peer_ids[2], uint128(500), uint32(1), True)
    assert len(store.get_peak_of_each_peer()) == 3
    assert store.get_peak_of_each_peer()[peer_ids[0]].weight == 500
    assert store.get_peak_of_each_peer()[peer_ids[1]].weight == 300
    assert store.get_peak_of_each_peer()[peer_ids[2]].weight == 500

    assert store.get_peers_that_have_peak([std_hash(b"block1")]) == set(peer_ids)
    assert store.get_peers_that_have_peak([std_hash(b"block10")]) == {peer_ids[0], peer_ids[2]}

    store.peer_disconnected(peer_ids[0])
    peak = store.get_heaviest_peak()
    assert peak is not None
    assert peak.weight == 500
    assert len(store.get_peak_of_each_peer()) == 2
    assert store.get_peers_that_have_peak([std_hash(b"block10")]) == {peer_ids[2]}
    store.peer_disconnected(peer_ids[2])
    peak = store.get_heaviest_peak()
    assert peak is not None
    assert peak.weight == 300
    store.peer_has_block(std_hash(b"block30"), peer_ids[0], uint128(700), uint32(30), True)
    assert store.get_peak_of_each_peer()[peer_ids[0]].weight == 700
    peak = store.get_heaviest_peak()
    assert peak is not None
    assert peak.weight == 700


@pytest.mark.anyio
async def test_is_backtrack_syncing_works_when_not_present(seeded_random: random.Random) -> None:
    store = SyncStore()
    node_id = bytes32.random(r=seeded_random)

    assert node_id not in store._backtrack_syncing

    assert not store.is_backtrack_syncing(node_id=node_id)
    assert node_id not in store._backtrack_syncing


@pytest.mark.anyio
async def test_increment_backtrack_syncing_adds(seeded_random: random.Random) -> None:
    store = SyncStore()
    node_id = bytes32.random(r=seeded_random)

    assert node_id not in store._backtrack_syncing

    store.increment_backtrack_syncing(node_id=node_id)
    assert node_id in store._backtrack_syncing


@pytest.mark.anyio
async def test_increment_backtrack_syncing_increments(seeded_random: random.Random) -> None:
    store = SyncStore()
    node_id = bytes32.random(r=seeded_random)

    store.increment_backtrack_syncing(node_id=node_id)
    store.increment_backtrack_syncing(node_id=node_id)
    assert store._backtrack_syncing[node_id] == 2


@pytest.mark.anyio
async def test_decrement_backtrack_syncing_does_nothing_when_not_present(
    seeded_random: random.Random,
) -> None:
    store = SyncStore()
    node_id = bytes32.random(r=seeded_random)

    assert node_id not in store._backtrack_syncing

    store.decrement_backtrack_syncing(node_id=node_id)
    assert node_id not in store._backtrack_syncing


@pytest.mark.anyio
async def test_decrement_backtrack_syncing_decrements(seeded_random: random.Random) -> None:
    store = SyncStore()
    node_id = bytes32.random(r=seeded_random)

    store._backtrack_syncing[node_id] = 2
    store.decrement_backtrack_syncing(node_id=node_id)
    assert store._backtrack_syncing[node_id] == 1


@pytest.mark.anyio
async def test_decrement_backtrack_syncing_removes_at_0(seeded_random: random.Random) -> None:
    store = SyncStore()
    node_id = bytes32.random(r=seeded_random)

    store._backtrack_syncing[node_id] = 1
    store.decrement_backtrack_syncing(node_id=node_id)
    assert node_id not in store._backtrack_syncing


@pytest.mark.anyio
async def test_backtrack_syncing_removes_on_disconnect(seeded_random: random.Random) -> None:
    store = SyncStore()
    node_id = bytes32.random(r=seeded_random)

    assert node_id not in store._backtrack_syncing

    store.increment_backtrack_syncing(node_id=node_id)
    assert node_id in store._backtrack_syncing

    store.peer_disconnected(node_id=node_id)
    assert node_id not in store._backtrack_syncing
