import unittest
from typing import List, Optional
from src.util.streamable import streamable
from src.util.ints import uint32


class TestStreamable(unittest.TestCase):
    def test_basic(self):
        @streamable
        class TestClass:
            a: uint32
            b: uint32
            c: List[uint32]
            d: List[List[uint32]]
            e: Optional[uint32]
            f: Optional[uint32]

        a = TestClass(24, 352, [1, 2, 4], [[1, 2, 3], [3, 4]], 728, None)

        b: bytes = a.serialize()
        assert a == TestClass.from_bytes(b)

    def test_variablesize(self):
        @streamable
        class TestClass2:
            a: uint32
            b: uint32
            c: str

        a = TestClass2(1, 2, "3")
        try:
            a.serialize()
            assert False
        except NotImplementedError:
            pass

        @streamable
        class TestClass3:
            a: int

        b = TestClass3(1)
        try:
            b.serialize()
            assert False
        except NotImplementedError:
            pass


if __name__ == '__main__':
    unittest.main()
