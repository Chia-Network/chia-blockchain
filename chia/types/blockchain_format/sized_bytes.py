from __future__ import annotations

from chia.util.byte_types import SizedBytes


class bytes4(SizedBytes):
    _size = 4


class bytes8(SizedBytes):
    _size = 8


class bytes32(SizedBytes):
    _size = 32


class bytes48(SizedBytes):
    _size = 48


class bytes96(SizedBytes):
    _size = 96


class bytes100(SizedBytes):
    _size = 100


class bytes480(SizedBytes):
    _size = 480
