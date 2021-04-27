import unittest

from chia.util.lru_cache import LRUCache


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
