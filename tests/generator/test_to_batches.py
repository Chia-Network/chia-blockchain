from __future__ import annotations

from typing import List

import pytest

from chia.util.generator_tools import to_batches


def test_empty_lists() -> None:
    # An empty list should return an empty iterator and skip the loop's body.
    empty: List[int] = []
    for _ in to_batches(empty, 1):
        assert False


@pytest.mark.parametrize("collection_type", [list, set])
def test_valid(collection_type: type) -> None:
    for k in range(1, 10):
        test_collection = collection_type([x for x in range(0, k)])
        for i in range(1, len(test_collection) + 1):  # Test batch_size 1 to 11 (length + 1)
            checked = 0
            for batch in to_batches(test_collection, i):
                assert batch.remaining == max(len(test_collection) - checked - i, 0)
                assert len(batch.entries) <= i
                entries = []
                for j, entry in enumerate(test_collection):
                    if j < checked:
                        continue
                    if j >= min(checked + i, len(test_collection)):
                        break
                    entries.append(entry)
                assert batch.entries == entries
                checked += len(batch.entries)
            assert checked == len(test_collection)


def test_invalid_batch_sizes() -> None:
    with pytest.raises(ValueError):
        for _ in to_batches([], 0):
            assert False
    with pytest.raises(ValueError):
        for _ in to_batches([], -1):
            assert False
