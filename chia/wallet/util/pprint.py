from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class Range:
    first: int
    last: int

    def __repr__(self) -> str:
        if self.first == self.last:
            return f"{self.first}"
        else:
            return f"{self.first} to {self.last}"


def int_list_to_ranges(array: List[int]) -> List[Range]:
    if len(array) == 0:
        return []
    sorted_array = sorted(array)
    first = sorted_array[0]
    last = first
    ranges = []
    for i in sorted_array[1:]:
        if i == last:
            pass
        elif i == last + 1:
            last = i
        else:
            ranges.append(Range(first, last))
            first = i
            last = i
    ranges.append(Range(first, last))
    return ranges


def print_compact_ranges(array: List[int]) -> str:
    return str(int_list_to_ranges(array))
