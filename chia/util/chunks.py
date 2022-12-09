from __future__ import annotations

from typing import Iterator, List, TypeVar

T = TypeVar("T")


def chunks(in_list: List[T], size: int) -> Iterator[List[T]]:
    size = max(1, size)
    for i in range(0, len(in_list), size):
        yield in_list[i : i + size]
