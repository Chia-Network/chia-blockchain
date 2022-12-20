from __future__ import annotations

import pytest

from chia.util.generator_tools import list_to_batches


def test_empty_lists():
    # An empty list should return an empty iterator and skip the loop's body.
    for _, _ in list_to_batches([], 1):
        assert False


def test_valid():
    for k in range(1, 10):
        test_list = [x for x in range(0, k)]
        for i in range(1, len(test_list) + 1):  # Test batch_size 1 to 11 (length + 1)
            checked = 0
            for remaining, batch in list_to_batches(test_list, i):
                assert remaining == max(len(test_list) - checked - i, 0)
                assert len(batch) <= i
                assert batch == test_list[checked : min(checked + i, len(test_list))]
                checked += len(batch)
            assert checked == len(test_list)


def test_invalid_batch_sizes():
    with pytest.raises(ValueError):
        for _ in list_to_batches([], 0):
            assert False
    with pytest.raises(ValueError):
        for _ in list_to_batches([], -1):
            assert False
