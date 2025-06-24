# This file converts between chialisp bytes and Python integer
from __future__ import annotations


def int_from_bytes(blob: bytes) -> int:
    size = len(blob)
    if size == 0:
        return 0
    return int.from_bytes(blob, "big", signed=True)


def int_to_bytes(v: int) -> bytes:
    byte_count = (v.bit_length() + 8) >> 3
    if v == 0:
        return b""
    r = v.to_bytes(byte_count, "big", signed=True)
    # make sure the string returned is minimal
    # ie. no leading 00 or ff bytes that are unnecessary
    while len(r) > 1 and r[0] == (0xFF if r[1] & 0x80 else 0):
        r = r[1:]
    return r
