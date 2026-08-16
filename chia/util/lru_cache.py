# Package: utils

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import KeysView
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

    def clear(self) -> None:
        self.cache.clear()

    def get_capacity(self) -> int:
        return self.capacity


class LRUSet(Generic[K]):
    """A bounded set that preserves insertion order and evicts the oldest entry when full."""

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._cache: dict[K, None] = {}

    def put(self, key: K) -> None:
        if key in self._cache:
            return
        if len(self._cache) >= self._capacity:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = None

    def remove(self, key: K) -> None:
        self._cache.pop(key, None)

    def get_capacity(self) -> int:
        return self._capacity

    def __contains__(self, key: K) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)


class LRUKeyedListCache(Generic[K, V]):
    """Bounded dict-of-lists with FIFO key eviction, per-key entry limits, and
    optional time-based expiry.

    Eviction is strictly FIFO by key insertion order — reading a key via
    ``get()`` or ``__getitem__()`` does **not** promote it.  This matches
    ``LRUSet`` above (the "LRU" prefix is a project convention for bounded
    evicting collections, not a guarantee of access-order promotion).

    Relies on ``dict`` preserving insertion order (Python 3.7+).  When a new key
    would exceed *max_keys*, the oldest key (first inserted) is evicted.  When a
    key already has *max_entries_per_key* values, further appends for that key
    are silently dropped.  Total entry count is tracked so callers never need to
    sum ``len(v)`` across keys.

    When *ttl_seconds* is set, each key stores a ``time.monotonic()`` timestamp
    alongside its value list (set once at key creation).  Because timestamps are
    never refreshed, dict iteration order matches timestamp order, so
    ``evict_expired()`` can stop at the first non-expired key.  Expired keys are
    evicted automatically at the start of each ``append()`` call and can also be
    purged explicitly via ``evict_expired()``.
    """

    def __init__(self, max_keys: int, max_entries_per_key: int, *, ttl_seconds: float | None = None) -> None:
        self._max_keys = max_keys
        self._max_entries_per_key = max_entries_per_key
        self._ttl_seconds = ttl_seconds
        self._data: dict[K, tuple[float, list[V]]] = {}
        self._total_entries = 0

    def evict_expired(self, cutoff: float | None = None) -> None:
        """Remove all keys whose timestamp is at or before *cutoff*.

        When *cutoff* is ``None`` it is computed as
        ``time.monotonic() - ttl_seconds``.  Does nothing when *ttl_seconds*
        was not set.  Exploits dict insertion order for an early stop.
        """
        if self._ttl_seconds is None:
            return
        if cutoff is None:
            cutoff = time.monotonic() - self._ttl_seconds
        while self._data:
            oldest_key, (ts, _entries) = next(iter(self._data.items()))
            if ts > cutoff:
                break
            self.pop(oldest_key)

    def append(self, key: K, value: V) -> bool:
        """Add *value* under *key*.  Returns ``True`` if stored."""
        stored, _evicted_key = self.append_with_evicted(key, value)
        return stored

    def append_with_evicted(self, key: K, value: V) -> tuple[bool, K | None]:
        """Add *value* under *key*. Returns ``(stored, evicted_key)``."""
        self.evict_expired()
        entry = self._data.get(key)
        evicted_key: K | None = None
        if entry is None:
            if len(self._data) >= self._max_keys:
                evicted_key = self._evict_oldest()
            entries: list[V] = []
            self._data[key] = (time.monotonic(), entries)
        else:
            entries = entry[1]
        if len(entries) >= self._max_entries_per_key:
            return False, evicted_key
        entries.append(value)
        self._total_entries += 1
        return True, evicted_key

    def get(self, key: K, default: list[V] | None = None) -> list[V]:
        """Return the list for *key*, or *default* (empty list when omitted)."""
        entry = self._data.get(key)
        if entry is not None:
            return entry[1]
        return default if default is not None else []

    def pop(self, key: K) -> list[V]:
        """Remove and return the list for *key*."""
        entry = self._data.pop(key, None)
        if entry is None:
            return []
        self._total_entries = max(0, self._total_entries - len(entry[1]))
        return entry[1]

    @property
    def total_entries(self) -> int:
        return self._total_entries

    def keys(self) -> KeysView[K]:
        return self._data.keys()

    def _evict_oldest(self) -> K | None:
        if self._data:
            oldest_key = next(iter(self._data))
            self.pop(oldest_key)
            return oldest_key
        return None

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, key: K) -> list[V]:
        return self._data[key][1]
