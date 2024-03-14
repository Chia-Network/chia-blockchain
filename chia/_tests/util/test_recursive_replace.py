from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import List, Optional, Union

import pytest

from chia.util.recursive_replace import recursive_replace


class TestC:
    a: int
    b: str

    def __init__(self, a: int, b: str):
        self.a = a
        self.b = b

    # WARNING: this is just a simple stand in for rust classes and is not a good
    # reference for how such a method should be implemented in python
    def replace(self, **kwargs: Union[int, str, Optional[TestA]]) -> TestC:
        ret = TestC(copy.deepcopy(self.a), copy.deepcopy(self.b))
        for key, value in kwargs.items():
            if key == "a":
                ret.a = value  # type: ignore[assignment]
            elif key == "b":  # pragma: no cover
                ret.b = value  # type: ignore[assignment]
            else:  # pragma: no cover
                raise TypeError(f"unknown field {key}")
        return ret


@dataclass
class TestA:
    a: int
    b: str
    c: List[int]
    d: Optional[TestC]


class TestB:
    a: int
    b: str
    c: Optional[TestA]

    def __init__(self, a: int, b: str, c: Optional[TestA]):
        self.a = a
        self.b = b
        self.c = c

    # WARNING: this is just a simple stand in for rust classes and is not a good
    # reference for how such a method should be implemented in python
    def replace(self, **kwargs: Union[int, str, Optional[TestA]]) -> TestB:
        ret = TestB(copy.deepcopy(self.a), copy.deepcopy(self.b), copy.deepcopy(self.c))
        for key, value in kwargs.items():
            if key == "a":  # pragma: no cover
                ret.a = value  # type: ignore[assignment]
            elif key == "b":
                ret.b = value  # type: ignore[assignment]
            elif key == "c":
                ret.c = value  # type: ignore[assignment]
            else:
                raise TypeError(f"unknown field {key}")
        return ret

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TestB):
            return self.a == other.a and self.b == other.b and self.c == self.c
        else:
            return False  # pragma: no cover


def test_recursive_replace_dataclass() -> None:
    a = TestA(42, "foobar", [1337, 42], None)
    a2 = recursive_replace(a, "b", "barfoo")

    assert a.a == a2.a
    assert a.b == "foobar"
    assert a2.b == "barfoo"
    assert a.c == a2.c


def test_recursive_replace_other() -> None:
    b = TestB(42, "foobar", None)
    b2 = recursive_replace(b, "b", "barfoo")

    assert b.a == b2.a
    assert b.b == "foobar"
    assert b2.b == "barfoo"
    assert b.c == b2.c


def test_recursive_replace() -> None:
    b1 = TestB(42, "foobar", TestA(1337, "barfoo", [1, 2, 3], None))
    b2 = recursive_replace(b1, "c.a", 110)

    assert b1 == TestB(42, "foobar", TestA(1337, "barfoo", [1, 2, 3], None))
    assert b2 == TestB(42, "foobar", TestA(110, "barfoo", [1, 2, 3], None))


def test_recursive_replace2() -> None:
    b1 = TestB(42, "foobar", TestA(1337, "barfoo", [1, 2, 3], TestC(123, "345")))
    b2 = recursive_replace(b1, "c.d.a", 110)

    assert b1 == TestB(42, "foobar", TestA(1337, "barfoo", [1, 2, 3], TestC(123, "345")))
    assert b2 == TestB(42, "foobar", TestA(1337, "barfoo", [1, 2, 3], TestC(110, "345")))


def test_recursive_replace_unknown() -> None:
    b = TestB(42, "foobar", TestA(1337, "barfoo", [1, 2, 3], None))
    with pytest.raises(TypeError):
        recursive_replace(b, "c.foobar", 110)

    with pytest.raises(TypeError):
        recursive_replace(b, "foobar", 110)
