from __future__ import annotations

import random

import pytest

from chia.types.blockchain_format.program import Program
from chia.util.casts import int_from_bytes, int_to_bytes


@pytest.mark.parametrize(
    "value",
    [
        0,
        1,
        -1,
        127,
        -127,
        128,
        -128,
        255,
        -255,
        256,
        -256,
        2**8 - 1,
        -(2**8) + 1,
        2**15,
        -(2**15),
        2**31 - 1,
        -(2**31),
        2**63 - 1,
        -(2**63),
        2**127 - 1,
        -(2**127),
        10**100,
        -(10**100),  # big ints
    ],
)
def test_round_trip(value: int) -> None:
    t1 = Program.to(value)
    t2 = int_to_bytes(value)
    assert t1 == Program.to(t2)
    assert int_from_bytes(t2) == value
    assert t1.as_int() == value


def test_zero_serialization() -> None:
    assert int_to_bytes(0) == b""
    assert int_from_bytes(b"") == 0


def test_minimal_encoding() -> None:
    assert int_to_bytes(0x80) == b"\x00\x80"
    assert int_to_bytes(-129) == b"\xff\x7f"  # no extra FF
    assert int_to_bytes(-128) == b"\x80"
    assert int_to_bytes(127) == b"\x7f"


def test_randomized() -> None:
    random.seed(97)
    for _ in range(1000):
        v = random.randint(-(2**256), 2**256)
        assert int_from_bytes(int_to_bytes(v)) == v


@pytest.mark.parametrize(
    "blob, expected",
    [
        (b"", 0),
        (b"\x00", 0),
        (b"\x7f", 127),
        (b"\x80", -128),
        (b"\xff", -1),
        (b"\x00\x80", 128),
        (b"\xff\x7f", -129),
    ],
)
def test_int_from_bytes_explicit(blob: bytes, expected: int) -> None:
    assert int_from_bytes(blob) == expected


def test_invertibility_on_large_values() -> None:
    for e in range(1, 1025, 64):
        v = 2**e
        for sign in [1, -1]:
            val = v * sign
            b = int_to_bytes(val)
            assert int_from_bytes(b) == val
