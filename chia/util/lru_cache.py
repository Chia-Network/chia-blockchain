# Package: utils

from __future__ import annotations

from collections import OrderedDict
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(Generic[K, V]):
    def __init__(self, capacity: int):
        self.cache: OrderedDict[K, V] = OrderedDict()
        self.capacity = capacity

    def get(self, key: K) -> V | None:
        if key not in self.cache:
            return None
        else:
            self.cache.move_to_end(key)
            return self.cache[key]

    def put(self, key: K, value: V) -> None:
        if self.capacity > 0:
            self.cache[key] = value
            self.cache.move_to_end(key)
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    def remove(self, key: K) -> None:
        self.cache.pop(key)

    def get_capacity(self) -> int:
        return self.capacity


class LRUSet(Generic[K]):
    """A bounded set that preserves insertion order and evicts the oldest entry when full."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.cache: dict[K, None] = {}

    def put(self, key: K) -> None:
        if key in self.cache:
            return
        if len(self.cache) >= self.capacity:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = None

    def remove(self, key: K) -> None:
        self.cache.pop(key, None)

    def get_capacity(self) -> int:
        return self.capacity

    def __contains__(self, key: K) -> bool:
        return key in self.cache

    def __len__(self) -> int:
        return len(self.cache)
