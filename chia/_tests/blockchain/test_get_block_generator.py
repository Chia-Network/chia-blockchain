from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32
from clvm.casts import int_to_bytes

from chia.consensus.get_block_generator import get_block_generator
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.generator_types import BlockGenerator


@dataclass(frozen=True)
class BR:
    prev_header_hash: bytes32
    transactions_generator: Optional[SerializedProgram]
    transactions_generator_ref_list: list[uint32]


@dataclass(frozen=True)
class FB:
    prev_header_hash: bytes32
    transactions_generator: Optional[SerializedProgram]
    height: uint32


def blockhash(i: int) -> bytes32:
    return bytes32([i] * 32)


def program(i: int) -> SerializedProgram:
    return SerializedProgram.from_bytes(int_to_bytes(i))


async def zero_hits(hh: bytes32, refs: set[uint32]) -> dict[uint32, bytes]:
    return {}


async def never_called(hh: bytes32, refs: set[uint32]) -> dict[uint32, bytes]:
    assert False  # pragma: no cover


async def only_lookup_5(hh: bytes32, refs: set[uint32]) -> dict[uint32, bytes]:
    assert refs == {uint32(5)}
    return {uint32(5): bytes(program(5))}


DUMMY_PROGRAM = SerializedProgram.from_bytes(b"\x80")


@pytest.mark.anyio
async def test_failing_lookup() -> None:
    br = BR(bytes32.zeros, DUMMY_PROGRAM, [uint32(1)])
    with pytest.raises(KeyError):
        await get_block_generator(zero_hits, br)


@pytest.mark.anyio
async def test_no_generator() -> None:
    br = BR(bytes32.zeros, None, [uint32(1)])
    with pytest.raises(AssertionError):
        await get_block_generator(zero_hits, br)


@pytest.mark.anyio
async def test_no_refs() -> None:
    br = BR(bytes32.zeros, DUMMY_PROGRAM, [])
    bg = await get_block_generator(never_called, br)
    assert bg == BlockGenerator(DUMMY_PROGRAM, [])
