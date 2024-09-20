from __future__ import annotations

from typing import List, Set

# Utility Functions for Collections & Sequences


def find_duplicates(array: List[int]) -> Set[int]:
    seen = set()
    duplicates = set()

    for i in array:
        if i in seen:
            duplicates.add(i)
        seen.add(i)

    return duplicates
