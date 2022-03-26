import unittest
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from pytest import raises

from chia.util.ints import uint8
from chia.util.type_checking import is_type_List, is_type_SpecificOptional, strictdataclass


class TestIsTypeList(unittest.TestCase):
    def test_basic_list(self):
        a = [1, 2, 3]
        assert is_type_List(type(a))
        assert is_type_List(List)
        assert is_type_List(List[int])
        assert is_type_List(List[uint8])
        assert is_type_List(list)
        assert not is_type_List(Tuple)
        assert not is_type_List(tuple)
        assert not is_type_List(dict)

    def test_not_lists(self):
        assert not is_type_List(Dict)


class TestIsTypeSpecificOptional(unittest.TestCase):
    def test_basic_optional(self):
        assert is_type_SpecificOptional(Optional[int])
        assert is_type_SpecificOptional(Optional[Optional[int]])
        assert not is_type_SpecificOptional(List[int])


class TestStrictClass(unittest.TestCase):
    def test_StrictDataClass(self):
        @dataclass(frozen=True)
        @strictdataclass
        class TestClass1:
            a: int
            b: str

        good: TestClass1 = TestClass1(24, "!@12")
        assert TestClass1.__name__ == "TestClass1"
        assert good
        assert good.a == 24
        assert good.b == "!@12"
        good2 = TestClass1(52, bytes([1, 2, 3]))
        assert good2.b == str(bytes([1, 2, 3]))

    def test_StrictDataClassBad(self):
        @dataclass(frozen=True)
        @strictdataclass
        class TestClass2:
            a: int
            b = 0

        assert TestClass2(25)

        with raises(TypeError):
            TestClass2(1, 2)  # pylint: disable=too-many-function-args

    def test_StrictDataClassLists(self):
        @dataclass(frozen=True)
        @strictdataclass
        class TestClass:
            a: List[int]
            b: List[List[uint8]]

        assert TestClass([1, 2, 3], [[uint8(200), uint8(25)], [uint8(25)]])

        with raises(ValueError):
            TestClass({"1": 1}, [[uint8(200), uint8(25)], [uint8(25)]])

        with raises(ValueError):
            TestClass([1, 2, 3], [uint8(200), uint8(25)])

    def test_StrictDataClassOptional(self):
        @dataclass(frozen=True)
        @strictdataclass
        class TestClass:
            a: Optional[int]
            b: Optional[int]
            c: Optional[Optional[int]]
            d: Optional[Optional[int]]

        good = TestClass(12, None, 13, None)
        assert good


if __name__ == "__main__":
    unittest.main()
