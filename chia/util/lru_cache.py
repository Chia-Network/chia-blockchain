from __future__ import annotations

from collections import OrderedDict
from typing import Generic, Optional, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(Generic[K, V]):
    def __init__(self, capacity: int):
        self.cache: OrderedDict[K, V] = OrderedDict()
        self.capacity = capacity

    def get(self, key: K) -> Optional[V]:
        if key not in self.cache:
            return None
        else:
            self.cache.move_to_end(key)
            return self.cache[key]

    def put(self, key: K, value: V) -> None:
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def remove(self, key: K) -> None:
        self.cache.pop(key)
