import unittest

from src.util.dpath_dict import DPathDict

L = [5, 6, 7]


class TestDPathDict(unittest.TestCase):
    def base_d(self):
        d = {
            "k0": "foo",
            "k1": "bar",
            "k2": {"j0": "baz", "j1": {"i0": L, "i2": 50, "i9": 999}},
        }
        return DPathDict(d)

    def test_1(self):
        d0 = self.base_d()
        assert d0.get_dpath("k0") == "foo"
        assert d0.get_dpath("k1") == "bar"
        assert d0.get_dpath("k2.j0") == "baz"
        assert d0.get_dpath("k2.j1.i0") == L

    def test_2(self):
        d0 = self.base_d()
        assert d0.get_dpath("k0") == "foo"
        assert d0.get_dpath("k1") == "bar"
        assert d0.get_dpath("k2.j0") == "baz"
        assert d0.get_dpath("k2.j1.i0") == L
        d0.set_dpath("k2.j5.i9", 1000)
        assert d0.get_dpath("k2.j5.i9") == 1000
        assert isinstance(d0.get_dpath("k2.j1"), dict)
        assert d0.get_dpath("k2.j8") is None
        assert d0.get_dpath("k2.j8.foo") is None
        assert d0.get_dpath("k2.j8.foo", "anything") == "anything"

    def test_paths(self):
        d0 = self.base_d()
        paths = list(d0.dpaths())
        assert paths == ["k0", "k1", "k2.j0", "k2.j1.i0", "k2.j1.i2", "k2.j1.i9"]
