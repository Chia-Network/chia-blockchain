from __future__ import annotations

from chia.util.collection import find_duplicates


def test_find_duplicates() -> None:
    assert find_duplicates([]) == set()
    assert find_duplicates([1, 1]) == {1}
    assert find_duplicates([3, 2, 1]) == set()
    assert find_duplicates([1, 2, 3]) == set()
    assert find_duplicates([1, 2, 3, 2, 1]) == {1, 2}
