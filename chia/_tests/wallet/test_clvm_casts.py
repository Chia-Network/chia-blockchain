from chia.types.blockchain_format.program import Program
import pytest
import random

from chia.wallet.util.casts import int_from_bytes, int_to_bytes

@pytest.mark.parametrize("value", [
    0,
    1, -1,
    127, -127,
    128, -128,
    255, -255,
    256, -256,
    2**8 - 1, -2**8 + 1,
    2**15, -2**15,
    2**31 - 1, -2**31,
    2**63 - 1, -2**63,
    2**127 - 1, -2**127,
    10**100, -10**100,  # big ints
])
def test_round_trip(value):
    t1 = Program.to(value)
    t2 = int_to_bytes(value)
    assert t1 == Program.to(t2)
    assert int_from_bytes(t2) == value
    assert t1.as_int() == value

def test_zero_serialization():
    assert int_to_bytes(0) == b""
    assert int_from_bytes(b"") == 0

def test_minimal_encoding():
    assert int_to_bytes(0x80) == b"\x00\x80"
    assert int_to_bytes(-129) == b"\xFF\x7F"  # no extra FF
    assert int_to_bytes(-128) == b"\x80"
    assert int_to_bytes(127) == b"\x7F"

def test_randomized():
    for _ in range(1000):
        v = random.randint(-2**256, 2**256)
        assert int_from_bytes(int_to_bytes(v)) == v

@pytest.mark.parametrize("blob, expected", [
    (b"", 0),
    (b"\x00", 0),
    (b"\x7F", 127),
    (b"\x80", -128),
    (b"\xFF", -1),
    (b"\x00\x80", 128),
    (b"\xFF\x7F", -129),
])
def test_int_from_bytes_explicit(blob, expected):
    assert int_from_bytes(blob) == expected

def test_invertibility_on_large_values():
    for e in range(1, 1025, 64):
        v = 2 ** e
        for sign in [1, -1]:
            val = v * sign
            b = int_to_bytes(val)
            assert int_from_bytes(b) == val