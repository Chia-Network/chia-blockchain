from __future__ import annotations

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia._tests.util.db_connection import DBConnection
from chia.consensus.block_store_protocol import MMRState
from chia.consensus.mmr import MerkleMountainRange, leaf_index_to_pos
from chia.full_node.mmr_store import MMRStore
from chia.util.hash import std_hash

AGGREGATE_FROM = uint32(0)


def _leaf(i: int) -> bytes32:
    return std_hash(b"leaf" + i.to_bytes(4, "big"))


def _mmr_with_leaves(n: int) -> MerkleMountainRange:
    mmr = MerkleMountainRange()
    for i in range(n):
        mmr.append(_leaf(i))
    return mmr


def _state(mmr: MerkleMountainRange, canonical_height: int, canonical_hash: bytes32) -> MMRState:
    return MMRState(
        aggregate_from=AGGREGATE_FROM,
        leaf_count=mmr.leaf_count,
        canonical_height=uint32(canonical_height),
        canonical_header_hash=canonical_hash,
    )


class TestMMRStore:
    @pytest.mark.anyio
    async def test_empty(self) -> None:
        async with DBConnection(2) as db_wrapper:
            store = await MMRStore.create(db_wrapper)
            assert await store.get_state() is None
            assert await store.get_nodes() == []

    @pytest.mark.anyio
    async def test_append_persists_exactly_the_new_nodes(self) -> None:
        async with DBConnection(2) as db_wrapper:
            store = await MMRStore.create(db_wrapper)

            mmr = _mmr_with_leaves(4)
            state = _state(mmr, 3, _leaf(3))
            async with db_wrapper.writer():
                # a fresh persist writes the whole array starting at position 0
                await store.apply_canonical_update(0, list(mmr.nodes), state)

            assert await store.get_nodes() == list(mmr.nodes)
            assert await store.get_state() == state

            # appending one more leaf only adds the newly created flat nodes
            old_node_count = len(mmr.nodes)
            mmr.append(_leaf(4))
            new_nodes = list(mmr.nodes[old_node_count:])
            new_state = _state(mmr, 4, _leaf(4))
            async with db_wrapper.writer():
                await store.apply_canonical_update(old_node_count, new_nodes, new_state)

            assert await store.get_nodes() == list(mmr.nodes)
            assert await store.get_state() == new_state

    @pytest.mark.anyio
    async def test_reorg_truncates_suffix_and_appends_new_branch(self) -> None:
        async with DBConnection(2) as db_wrapper:
            store = await MMRStore.create(db_wrapper)

            # canonical chain of 5 leaves
            mmr = _mmr_with_leaves(5)
            async with db_wrapper.writer():
                await store.apply_canonical_update(0, list(mmr.nodes), _state(mmr, 4, _leaf(4)))

            # reorg: roll back to leaf index 1 (2 leaves), then extend a different branch
            fork_leaf_count = 2
            mmr.pop()
            mmr.pop()
            mmr.pop()
            assert mmr.leaf_count == fork_leaf_count
            truncation = len(mmr.nodes)

            mmr.append(_leaf(100))
            mmr.append(_leaf(101))
            mmr.append(_leaf(102))
            new_nodes = list(mmr.nodes[truncation:])
            new_state = _state(mmr, 4, _leaf(102))
            async with db_wrapper.writer():
                await store.apply_canonical_update(truncation, new_nodes, new_state)

            # the persisted array equals the rebuilt branch: shared prefix + new suffix
            expected = _mmr_with_leaves(2)
            for i in (100, 101, 102):
                expected.append(_leaf(i))
            assert await store.get_nodes() == list(expected.nodes)
            assert await store.get_state() == new_state

    @pytest.mark.anyio
    async def test_failed_transaction_leaves_state_unchanged(self) -> None:
        async with DBConnection(2) as db_wrapper:
            store = await MMRStore.create(db_wrapper)

            mmr = _mmr_with_leaves(3)
            state = _state(mmr, 2, _leaf(2))
            async with db_wrapper.writer():
                await store.apply_canonical_update(0, list(mmr.nodes), state)

            # a transaction that persists a further append and then fails must roll back
            bigger = _mmr_with_leaves(10)
            with pytest.raises(RuntimeError, match="boom"):
                async with db_wrapper.writer():
                    await store.apply_canonical_update(0, list(bigger.nodes), _state(bigger, 9, _leaf(9)))
                    raise RuntimeError("boom")

            # both the nodes and the singleton state are unchanged
            assert await store.get_nodes() == list(mmr.nodes)
            assert await store.get_state() == state

    @pytest.mark.anyio
    async def test_node_count_matches_leaf_count_invariant(self) -> None:
        # for n leaves the flat node count is 2n - popcount(n); the store round-trips it
        async with DBConnection(2) as db_wrapper:
            store = await MMRStore.create(db_wrapper)
            for n in (1, 2, 3, 7, 8, 9, 31):
                mmr = _mmr_with_leaves(n)
                assert len(mmr.nodes) == 2 * n - n.bit_count()
                async with db_wrapper.writer():
                    await store.apply_canonical_update(0, list(mmr.nodes), _state(mmr, n - 1, _leaf(n - 1)))
                loaded = await store.get_nodes()
                assert loaded == list(mmr.nodes)
                # leaves land at their flat positions
                for i in range(n):
                    assert loaded[leaf_index_to_pos(i)] == _leaf(i)
