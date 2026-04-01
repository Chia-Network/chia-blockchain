# Package: utils

from __future__ import annotations

# Utility Functions for Collections & Sequences


def find_duplicates(array: list[int]) -> set[int]:
    seen = set()
    duplicates = set()

    for i in array:
        if i in seen:
            duplicates.add(i)
        seen.add(i)

    return duplicates
