from __future__ import annotations

from dataclasses import dataclass
from typing import Collection, Generic, Iterator, List, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Batch(Generic[T]):
    remaining: int
    entries: List[T]


def to_batches(to_split: Collection[T], batch_size: int) -> Iterator[Batch[T]]:
    if batch_size <= 0:
        raise ValueError("to_batches: batch_size must be greater than 0.")
    total_size = len(to_split)
    if total_size == 0:
        return

    if isinstance(to_split, list):
        for batch_start in range(0, total_size, batch_size):
            batch_end = min(batch_start + batch_size, total_size)
            yield Batch(total_size - batch_end, to_split[batch_start:batch_end])
    elif isinstance(to_split, set):
        processed = 0
        entries = []
        for entry in to_split:
            entries.append(entry)
            if len(entries) >= batch_size:
                processed += len(entries)
                yield Batch(total_size - processed, entries)
                entries = []
        if len(entries) > 0:
            processed += len(entries)
            yield Batch(total_size - processed, entries)
    else:
        raise ValueError(f"to_batches: Unsupported type {type(to_split)}")
