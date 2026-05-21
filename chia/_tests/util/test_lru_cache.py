from __future__ import annotations

import time

import pytest

from chia.util.lru_cache import LRUKeyedListCache


class TestLRUKeyedListCache:
    def test_append_and_get(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=5)
        assert cache.append("a", 1)
        assert cache.append("a", 2)
        assert cache.get("a") == [1, 2]
        assert cache.total_entries == 2
        assert len(cache) == 1

    def test_get_missing_key_returns_empty(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=5)
        assert cache.get("missing") == []

    def test_get_missing_key_with_default(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=5)
        sentinel: list[int] = [99]
        assert cache.get("missing", sentinel) is sentinel

    def test_per_key_limit(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=3)
        for i in range(5):
            cache.append("k", i)
        assert cache["k"] == [0, 1, 2]
        assert cache.total_entries == 3

    def test_per_key_limit_returns_false_when_full(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=2)
        assert cache.append("k", 1) is True
        assert cache.append("k", 2) is True
        assert cache.append("k", 3) is False
        assert cache.total_entries == 2

    def test_max_keys_evicts_oldest(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=3, max_entries_per_key=10)
        cache.append("a", 1)
        cache.append("b", 2)
        cache.append("c", 3)
        assert len(cache) == 3

        cache.append("d", 4)
        assert len(cache) == 3
        assert "a" not in cache
        assert set(cache.keys()) == {"b", "c", "d"}
        assert cache.total_entries == 3

    def test_eviction_decrements_total_entries(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=2, max_entries_per_key=10)
        cache.append("a", 1)
        cache.append("a", 2)
        cache.append("b", 3)
        assert cache.total_entries == 3

        cache.append("c", 4)
        assert "a" not in cache
        assert cache.total_entries == 2

    def test_pop_returns_entries_and_clears(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=10)
        cache.append("x", 10)
        cache.append("x", 20)
        result = cache.pop("x")
        assert result == [10, 20]
        assert "x" not in cache
        assert cache.total_entries == 0

    def test_pop_missing_key(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=10)
        assert cache.pop("nope") == []
        assert cache.total_entries == 0

    def test_contains(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=10)
        assert "a" not in cache
        cache.append("a", 1)
        assert "a" in cache

    def test_getitem_raises_on_missing(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=10)
        with pytest.raises(KeyError):
            _ = cache["missing"]

    def test_keys_preserves_insertion_order(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=10)
        for k in ["c", "a", "b"]:
            cache.append(k, 1)
        assert list(cache.keys()) == ["c", "a", "b"]

    def test_multiple_evictions_on_bulk_insert(self) -> None:
        cache: LRUKeyedListCache[int, str] = LRUKeyedListCache(max_keys=3, max_entries_per_key=2)
        for i in range(6):
            cache.append(i, f"v{i}")
        assert len(cache) == 3
        assert set(cache.keys()) == {3, 4, 5}
        assert cache.total_entries == 3

    def test_append_with_evicted_returns_oldest_key(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=2, max_entries_per_key=10)
        assert cache.append_with_evicted("a", 1) == (True, None)
        assert cache.append_with_evicted("b", 2) == (True, None)
        assert cache.append_with_evicted("c", 3) == (True, "a")

    def test_append_with_evicted_returns_none_when_full_per_key(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=2, max_entries_per_key=1)
        assert cache.append_with_evicted("a", 1) == (True, None)
        assert cache.append_with_evicted("a", 2) == (False, None)

    def test_get_does_not_promote_key(self) -> None:
        """Eviction is FIFO by insertion order — reading a key does not protect it."""
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=3, max_entries_per_key=10)
        cache.append("a", 1)
        cache.append("b", 2)
        cache.append("c", 3)

        # Access "a" — should NOT move it to the back of the eviction queue.
        _ = cache.get("a")
        _ = cache["a"]

        # Insert "d" — "a" should still be evicted (oldest by insertion), not "b".
        cache.append("d", 4)
        assert "a" not in cache
        assert set(cache.keys()) == {"b", "c", "d"}

    def test_empty_cache(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=5, max_entries_per_key=5)
        assert len(cache) == 0
        assert cache.total_entries == 0
        assert cache.get("x") == []
        assert list(cache.keys()) == []

    def test_evict_oldest_on_empty_cache(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=5, max_entries_per_key=5)
        assert cache._evict_oldest() is None
        assert len(cache) == 0

    def test_evict_expired_with_cutoff(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=5, ttl_seconds=300)
        cache.append("a", 1)
        cache.append("b", 2)
        cache.evict_expired(cutoff=time.monotonic() + 1)
        assert len(cache) == 0
        assert cache.total_entries == 0

    def test_evict_expired_keeps_fresh(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=5, ttl_seconds=300)
        cache.append("a", 1)
        cache.evict_expired(cutoff=0)
        assert "a" in cache
        assert cache.total_entries == 1

    def test_evict_expired_selective(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=5, ttl_seconds=300)
        cache.append("old", 1)
        cutoff = time.monotonic()
        # Sleep must exceed the Windows timer tick (~15.6 ms) so that
        # time.monotonic() actually advances before the next append.
        time.sleep(0.05)
        cache.append("fresh", 2)
        cache.evict_expired(cutoff=cutoff)
        assert "old" not in cache
        assert "fresh" in cache
        assert cache.total_entries == 1

    def test_evict_expired_early_stop(self) -> None:
        """evict_expired stops iterating at the first non-expired key."""
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=5, ttl_seconds=300)
        cache.append("a", 1)
        cache.append("b", 2)
        cache.append("c", 3)
        cutoff = time.monotonic()
        # Sleep must exceed the Windows timer tick (~15.6 ms) so that
        # time.monotonic() actually advances before the next append.
        time.sleep(0.05)
        cache.append("d", 4)
        cache.append("e", 5)
        cache.evict_expired(cutoff=cutoff)
        assert "a" not in cache
        assert "b" not in cache
        assert "c" not in cache
        assert "d" in cache
        assert "e" in cache
        assert cache.total_entries == 2

    def test_evict_expired_noop_without_ttl(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=5)
        cache.append("a", 1)
        cache.evict_expired()
        assert "a" in cache

    def test_expired_evicted_on_append(self) -> None:
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=10, max_entries_per_key=5, ttl_seconds=0.05)
        cache.append("old", 1)
        time.sleep(0.1)
        cache.append("new", 2)
        assert "old" not in cache
        assert "new" in cache
        assert cache.total_entries == 1

    def test_ttl_eviction_frees_space_before_fifo(self) -> None:
        """When expired keys are evicted, a FIFO eviction of non-expired keys is avoided."""
        cache: LRUKeyedListCache[str, int] = LRUKeyedListCache(max_keys=2, max_entries_per_key=5, ttl_seconds=0.05)
        cache.append("a", 1)
        time.sleep(0.1)
        cache.append("b", 2)
        cache.append("c", 3)
        assert "a" not in cache
        assert "b" in cache
        assert "c" in cache
