from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import pytest
from clvm.casts import int_to_bytes

from chia.consensus.get_block_generator import get_block_generator
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.generator_types import BlockGenerator
from chia.util.ints import uint32


@dataclass(frozen=True)
class BR:
    prev_header_hash: bytes32
    transactions_generator: Optional[SerializedProgram]
    transactions_generator_ref_list: List[uint32]


@dataclass(frozen=True)
class FB:
    prev_header_hash: bytes32
    transactions_generator: Optional[SerializedProgram]
    height: uint32


def blockhash(i: int) -> bytes32:
    return bytes32([i] * 32)


def program(i: int) -> SerializedProgram:
    return SerializedProgram.from_bytes(int_to_bytes(i))


async def zero_hits(hh: bytes32, refs: Set[uint32]) -> Dict[uint32, bytes]:
    return {}


async def never_called(hh: bytes32, refs: Set[uint32]) -> Dict[uint32, bytes]:
    assert False  # pragma: no cover


async def only_lookup_5(hh: bytes32, refs: Set[uint32]) -> Dict[uint32, bytes]:
    assert refs == {uint32(5)}
    return {uint32(5): bytes(program(5))}


DUMMY_PROGRAM = SerializedProgram.from_bytes(b"\x80")


@pytest.mark.anyio
async def test_failing_lookup() -> None:
    br = BR(bytes32([0] * 32), DUMMY_PROGRAM, [uint32(1)])
    with pytest.raises(KeyError):
        await get_block_generator(zero_hits, br, {})


@pytest.mark.anyio
async def test_no_generator() -> None:
    br = BR(bytes32([0] * 32), None, [uint32(1)])
    with pytest.raises(AssertionError):
        await get_block_generator(zero_hits, br, {})


@pytest.mark.anyio
async def test_no_refs() -> None:
    br = BR(bytes32([0] * 32), DUMMY_PROGRAM, [])
    bg = await get_block_generator(never_called, br, {})
    assert bg == BlockGenerator(DUMMY_PROGRAM, [])


@pytest.mark.anyio
async def test_ref_has_no_generator() -> None:

    additional: Dict[bytes32, FB] = {}
    additional[blockhash(0)] = FB(blockhash(0), None, uint32(1))

    br = BR(blockhash(0), DUMMY_PROGRAM, [uint32(1)])
    with pytest.raises(ValueError, match="GENERATOR_REF_HAS_NO_GENERATOR"):
        await get_block_generator(never_called, br, additional)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_additional_blocks() -> None:

    additional: Dict[bytes32, FB] = {}
    additional[blockhash(0)] = FB(blockhash(100), program(1), uint32(1))
    additional[blockhash(1)] = FB(blockhash(0), program(2), uint32(2))
    additional[blockhash(2)] = FB(blockhash(1), program(3), uint32(3))

    br = BR(blockhash(2), DUMMY_PROGRAM, [uint32(1), uint32(3)])
    bg = await get_block_generator(never_called, br, additional)  # type: ignore[arg-type]
    assert bg == BlockGenerator(DUMMY_PROGRAM, [bytes(program(1)), bytes(program(3))])

    br = BR(blockhash(2), DUMMY_PROGRAM, [uint32(3), uint32(1)])
    bg = await get_block_generator(never_called, br, additional)  # type: ignore[arg-type]
    assert bg == BlockGenerator(DUMMY_PROGRAM, [bytes(program(3)), bytes(program(1))])

    br = BR(blockhash(2), DUMMY_PROGRAM, [uint32(3), uint32(1), uint32(2)])
    bg = await get_block_generator(never_called, br, additional)  # type: ignore[arg-type]
    assert bg == BlockGenerator(DUMMY_PROGRAM, [bytes(program(3)), bytes(program(1)), bytes(program(2))])


@pytest.mark.anyio
async def test_fallback() -> None:

    additional: Dict[bytes32, FB] = {}
    additional[blockhash(10)] = FB(blockhash(9), program(10), uint32(10))
    additional[blockhash(9)] = FB(blockhash(8), program(9), uint32(9))
    additional[blockhash(8)] = FB(blockhash(7), program(8), uint32(8))
    additional[blockhash(7)] = FB(blockhash(6), program(7), uint32(7))
    additional[blockhash(6)] = FB(blockhash(5), program(6), uint32(6))

    br = BR(blockhash(10), DUMMY_PROGRAM, [uint32(7), uint32(5), uint32(9)])
    bg = await get_block_generator(only_lookup_5, br, additional)  # type: ignore[arg-type]
    assert bg == BlockGenerator(DUMMY_PROGRAM, [bytes(program(7)), bytes(program(5)), bytes(program(9))])
