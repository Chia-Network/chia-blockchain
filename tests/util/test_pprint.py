from __future__ import annotations

from chia.util.pprint import print_compact_ranges


def test_print_compact_ranges() -> None:
    assert print_compact_ranges([]) == "[]"
    assert print_compact_ranges([1]) == "[1]"
    assert print_compact_ranges([1, 2]) == "[1 to 2]"
    assert print_compact_ranges([2, 1]) == "[1 to 2]"
    assert print_compact_ranges([1, 3, 4]) == "[1, 3 to 4]"
    assert print_compact_ranges([1, 2, 4]) == "[1 to 2, 4]"
    assert print_compact_ranges([1, 2, 4, 5]) == "[1 to 2, 4 to 5]"

    assert print_compact_ranges([-1, -2]) == "[-2 to -1]"

    assert print_compact_ranges([1, 1, 1, 2, 2, 4, 4, 9]) == "[1 to 2, 4, 9]"
