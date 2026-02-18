from __future__ import annotations

import unittest

import pytest

from chia.util.lru_cache import LRUCache, LRUSet


class TestLRUCache(unittest.TestCase):
    def test_lru_cache(self):
        cache = LRUCache(5)

        assert cache.get(b"0") is None

        assert len(cache.cache) == 0
        cache.put(b"0", 1)
        assert len(cache.cache) == 1
        assert cache.get(b"0") == 1
        cache.put(b"0", 2)
        cache.put(b"0", 3)
        cache.put(b"0", 4)
        cache.put(b"0", 6)
        assert cache.get(b"0") == 6
        assert len(cache.cache) == 1

        cache.put(b"1", 1)
        assert len(cache.cache) == 2
        assert cache.get(b"0") == 6
        assert cache.get(b"1") == 1
        cache.put(b"2", 2)
        assert len(cache.cache) == 3
        assert cache.get(b"0") == 6
        assert cache.get(b"1") == 1
        assert cache.get(b"2") == 2
        cache.put(b"3", 3)
        assert len(cache.cache) == 4
        assert cache.get(b"0") == 6
        assert cache.get(b"1") == 1
        assert cache.get(b"2") == 2
        assert cache.get(b"3") == 3
        cache.put(b"4", 4)
        assert len(cache.cache) == 5
        assert cache.get(b"0") == 6
        assert cache.get(b"1") == 1
        assert cache.get(b"2") == 2
        assert cache.get(b"4") == 4
        cache.put(b"5", 5)
        assert cache.get(b"5") == 5
        assert len(cache.cache) == 5
        print(cache.cache)
        assert cache.get(b"3") is None  # 3 is least recently used
        assert cache.get(b"1") == 1
        assert cache.get(b"2") == 2
        cache.put(b"7", 7)
        assert len(cache.cache) == 5
        assert cache.get(b"0") is None
        assert cache.get(b"1") == 1


@pytest.mark.parametrize(argnames="capacity", argvalues=[-10, -1, 0])
def test_with_zero_capacity(capacity: int) -> None:
    cache: LRUCache[bytes, int] = LRUCache(capacity=capacity)
    cache.put(b"0", 1)
    assert cache.get(b"0") is None
    assert len(cache.cache) == 0


@pytest.mark.parametrize(argnames="capacity", argvalues=[-10, -1, 0, 1, 5, 10])
def test_get_capacity(capacity: int) -> None:
    cache: LRUCache[object, object] = LRUCache(capacity=capacity)
    assert cache.get_capacity() == capacity


class TestLRUSet:
    def test_put_and_contains(self) -> None:
        s: LRUSet[str] = LRUSet(5)
        assert "a" not in s
        assert len(s) == 0

        s.put("a")
        assert "a" in s
        assert len(s) == 1

        s.put("b")
        s.put("c")
        assert len(s) == 3
        assert "a" in s
        assert "b" in s
        assert "c" in s

    def test_duplicate_put(self) -> None:
        s: LRUSet[str] = LRUSet(5)
        s.put("a")
        s.put("a")
        s.put("a")
        assert len(s) == 1
        assert "a" in s

    def test_remove(self) -> None:
        s: LRUSet[str] = LRUSet(5)
        s.put("a")
        s.put("b")
        s.remove("a")
        assert "a" not in s
        assert "b" in s
        assert len(s) == 1

    def test_remove_missing_key(self) -> None:
        s: LRUSet[str] = LRUSet(5)
        s.remove("nonexistent")
        assert len(s) == 0

    def test_eviction_order(self) -> None:
        s: LRUSet[str] = LRUSet(3)
        s.put("a")
        s.put("b")
        s.put("c")
        assert len(s) == 3

        # adding a 4th element evicts the oldest ("a")
        s.put("d")
        assert len(s) == 3
        assert "a" not in s
        assert "b" in s
        assert "c" in s
        assert "d" in s

        # adding a 5th evicts "b"
        s.put("e")
        assert len(s) == 3
        assert "b" not in s
        assert "c" in s
        assert "d" in s
        assert "e" in s

    def test_duplicate_does_not_reset_insertion_order(self) -> None:
        s: LRUSet[str] = LRUSet(3)
        s.put("a")
        s.put("b")
        s.put("c")

        # re-adding "a" should NOT move it to the end
        s.put("a")
        assert len(s) == 3

        # so adding a new element should still evict "a" (the oldest)
        s.put("d")
        assert "a" not in s
        assert "b" in s
        assert "c" in s
        assert "d" in s

    def test_remove_frees_slot(self) -> None:
        s: LRUSet[str] = LRUSet(3)
        s.put("a")
        s.put("b")
        s.put("c")
        s.remove("b")
        assert len(s) == 2

        # adding after remove should not trigger eviction
        s.put("d")
        assert len(s) == 3
        assert "a" in s
        assert "c" in s
        assert "d" in s

    def test_capacity_one(self) -> None:
        s: LRUSet[str] = LRUSet(1)
        s.put("a")
        assert "a" in s
        assert len(s) == 1

        s.put("b")
        assert "a" not in s
        assert "b" in s
        assert len(s) == 1

    def test_get_capacity(self) -> None:
        for cap in [1, 5, 100]:
            s: LRUSet[str] = LRUSet(cap)
            assert s.get_capacity() == cap
