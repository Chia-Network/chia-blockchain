from collections import OrderedDict
from typing import Any, Optional


class LRUCache:
    def __init__(self, capacity: int):
        self.cache: OrderedDict = OrderedDict()
        self.capacity = capacity

    def get(self, key: Any) -> Optional[Any]:
        if key not in self.cache:
            return None
        else:
            self.cache.move_to_end(key)
            return self.cache[key]

    def put(self, key: Any, value: Any) -> None:
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def remove(self, key: Any) -> None:
        self.cache.pop(key)
