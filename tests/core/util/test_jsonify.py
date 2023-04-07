from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32
from chia.util.streamable import Streamable, recurse_jsonify, streamable


def dict_with_types(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: (v, type(v)) for k, v in d.items()}


def test_primitives() -> None:
    @streamable
    @dataclass(frozen=True)
    class PrimitivesTest(Streamable):
        a: uint32
        b: Optional[str]
        c: str
        d: bytes
        e: bytes32
        f: bool

    t1 = PrimitivesTest(
        uint32(123),
        None,
        "foobar",
        b"\0\1\0\1",
        bytes32(range(32)),
        True,
    )

    assert dict_with_types(t1.to_json_dict()) == {
        "a": (123, int),
        "b": (None, type(None)),
        "c": ("foobar", str),
        "d": ("0x00010001", str),
        "e": ("0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", str),
        "f": (True, bool),
    }

    t2 = PrimitivesTest(
        uint32(0),
        "set optional",
        "foobar",
        b"\0\1",
        bytes32([0] * 32),
        False,
    )

    assert dict_with_types(t2.to_json_dict()) == {
        "a": (0, int),
        "b": ("set optional", str),
        "c": ("foobar", str),
        "d": ("0x0001", str),
        "e": ("0x0000000000000000000000000000000000000000000000000000000000000000", str),
        "f": (False, bool),
    }


def test_list() -> None:
    @streamable
    @dataclass(frozen=True)
    class ListTest(Streamable):
        d: List[str]

    t = ListTest(["foo", "bar"])

    assert t.to_json_dict() == {"d": ["foo", "bar"]}


def test_tuple() -> None:
    @streamable
    @dataclass(frozen=True)
    class TupleTest(Streamable):
        d: Tuple[str, uint32, str]

    t = TupleTest(("foo", uint32(123), "bar"))

    assert t.to_json_dict() == {"d": ["foo", 123, "bar"]}


@streamable
@dataclass(frozen=True)
class NestedWithTupleInner(Streamable):
    a: Tuple[str, uint32, str]
    b: bytes


@streamable
@dataclass(frozen=True)
class NestedWithTupleOuter(Streamable):
    a: Tuple[NestedWithTupleInner, uint32, str]


def test_nested_with_tuple() -> None:
    t = NestedWithTupleOuter(
        (NestedWithTupleInner(("foo", uint32(123), "bar"), bytes([0x13, 0x37])), uint32(321), "baz")
    )

    assert t.to_json_dict() == {"a": [{"a": ["foo", 123, "bar"], "b": "0x1337"}, 321, "baz"]}


@streamable
@dataclass(frozen=True)
class NestedWithListInner(Streamable):
    a: uint32
    b: bytes


@streamable
@dataclass(frozen=True)
class NestedWithListOuter(Streamable):
    a: List[NestedWithListInner]


def test_nested_with_list() -> None:
    t = NestedWithListOuter([NestedWithListInner(uint32(123), bytes([0x13, 0x37]))])

    assert t.to_json_dict() == {"a": [{"a": 123, "b": "0x1337"}]}


@streamable
@dataclass(frozen=True)
class TestNestedInner(Streamable):
    a: Tuple[str, uint32, str]
    b: bytes


@streamable
@dataclass(frozen=True)
class TestNestedOuter(Streamable):
    a: TestNestedInner


def test_nested() -> None:
    t = TestNestedOuter(TestNestedInner(("foo", uint32(123), "bar"), bytes([0x13, 0x37])))

    assert t.to_json_dict() == {"a": {"a": ["foo", 123, "bar"], "b": "0x1337"}}


def test_recurse_jsonify() -> None:
    d = {"a": "foo", "b": bytes([0x13, 0x37]), "c": [uint32(1), uint32(2)], "d": {"bar": None}}
    assert recurse_jsonify(d) == {"a": "foo", "b": "0x1337", "c": [1, 2], "d": {"bar": None}}
