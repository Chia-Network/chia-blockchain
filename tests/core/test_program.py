from __future__ import annotations

from typing import List

from clvm.SExp import CastableType
from clvm_tools import binutils

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64


def program_roundtrip(o: CastableType) -> None:
    prg1 = Program.to(o)
    prg2 = SerializedProgram.to(o)
    prg3 = SerializedProgram.from_program(prg1)
    prg4 = SerializedProgram.from_bytes(prg1.as_bin())
    prg5 = prg2.to_program()

    assert bytes(prg1) == bytes(prg2)
    assert bytes(prg1) == bytes(prg3)
    assert bytes(prg1) == bytes(prg4)
    assert bytes(prg1) == bytes(prg5)


def test_serialized_program_to() -> None:
    prg = "(q ((0x0101010101010101010101010101010101010101010101010101010101010101 80 123 (() (q . ())))))"  # noqa
    tests: List[CastableType] = [
        0,
        1,
        (1, 2),
        [0, 1, 2],
        Program.to([1, 2, 3]),
        SerializedProgram.to([1, 2, 3]),
        b"123",
        binutils.assemble(prg),  # type: ignore[no-untyped-call]
        [b"1", b"2", b"3"],
        (b"1", (b"2", b"3")),
        None,
        -24,
        bytes32.fromhex("0" * 64),
        bytes.fromhex("0" * 6),
        uint32(123),
        uint64(123123),
    ]

    for t in tests:
        program_roundtrip(t)
