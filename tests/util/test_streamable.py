import unittest
from dataclasses import dataclass
from typing import List, Optional

from src.util.ints import uint32
from src.util.streamable import Streamable, streamable


class TestStreamable(unittest.TestCase):
    def test_basic(self):
        @dataclass(frozen=True)
        @streamable
        class TestClass(Streamable):
            a: uint32
            b: uint32
            c: List[uint32]
            d: List[List[uint32]]
            e: Optional[uint32]
            f: Optional[uint32]

        a = TestClass(24, 352, [1, 2, 4], [[1, 2, 3], [3, 4]], 728, None)  # type: ignore

        b: bytes = bytes(a)
        assert a == TestClass.from_bytes(b)

    def test_variablesize(self):
        @dataclass(frozen=True)
        @streamable
        class TestClass2(Streamable):
            a: uint32
            b: uint32
            c: str

        a = TestClass2(uint32(1), uint32(2), "3")
        try:
            bytes(a)
            assert False
        except NotImplementedError:
            pass

        @dataclass(frozen=True)
        @streamable
        class TestClass3(Streamable):
            a: int

        b = TestClass3(1)
        try:
            bytes(b)
            assert False
        except NotImplementedError:
            pass


if __name__ == "__main__":
    unittest.main()
