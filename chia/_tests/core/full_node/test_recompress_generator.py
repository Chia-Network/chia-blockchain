from __future__ import annotations

import pytest
from chia_rs import (
    INTERNED_SPEND_LIST,
    SERDE_2026_MAGIC_PREFIX,
    Coin,
    G2Element,
    get_flags_for_height_and_constants,
    run_block_generator2,
    solution_generator_2026,
    tree_hash_2026,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import recompress_generator
from chia.types.blockchain_format.program import Program

CONSTANTS = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(0))
FLAGS = get_flags_for_height_and_constants(0, CONSTANTS)
PUZZLE = Program.to(1)
SOLUTION = Program.to([[51, bytes32([7] * 32), 5]])
COINS = [Coin(bytes32([i + 1] * 32), PUZZLE.get_tree_hash(), uint64(1000 + i)) for i in range(3)]
SPENDS = [(coin, bytes(PUZZLE), bytes(SOLUTION)) for coin in COINS]
CANONICAL = solution_generator_2026(SPENDS)


def varint(v: int, size: int | None = None) -> bytes:
    # serde_2026 varint: the count of leading 1 bits in the first byte is the
    # count of extra bytes. `size` forces a longer (overlong) encoding.
    extra = 0
    while not (-(1 << (6 + 7 * extra)) <= v < (1 << (6 + 7 * extra))):
        extra += 1
    if size is not None:
        assert size - 1 >= extra
        extra = size - 1
    u = v + (1 << (7 + 7 * extra)) if v < 0 else v
    first = (((1 << extra) - 1) << (8 - extra)) & 0xFF
    return bytes([first | (u >> (8 * extra))] + [(u >> (8 * i)) & 0xFF for i in reversed(range(extra))])


def encode_plain(tree: Program, varint_size: int | None = None) -> bytes:
    # serde_2026 encoding with one atom group per atom and no back-references
    atoms: list[bytes] = []
    insts: list[int] = []

    def walk(node: Program) -> None:
        if node.atom is None:
            walk(node.first())
            walk(node.rest())
            insts.append(1)
        elif node.atom == b"":
            insts.append(0)
        else:
            atoms.append(bytes(node.atom))
            insts.append(len(atoms) + 1)

    walk(tree)
    out = bytearray(SERDE_2026_MAGIC_PREFIX)
    out += varint(len(atoms), varint_size)
    for atom in atoms:
        out += varint(len(atom), varint_size) + atom
    out += varint(len(insts), varint_size)
    for inst in insts:
        out += varint(inst, varint_size)
    return bytes(out)


def spend_list() -> Program:
    # solution_generator_2026 lists the spends in reverse order
    return Program.to([[c.parent_coin_info, PUZZLE, c.amount, SOLUTION] for c, _, _ in reversed(SPENDS)])


def canonical_tree() -> Program:
    # the generator is a one-element list holding the spend list
    return Program.to([spend_list()])


def test_encode_plain_matches_tree() -> None:
    assert FLAGS & INTERNED_SPEND_LIST
    assert tree_hash_2026(encode_plain(canonical_tree())) == tree_hash_2026(CANONICAL)


def test_round_trip() -> None:
    # the canonical encoding is already as small as the re-encoding
    assert recompress_generator(CANONICAL, CONSTANTS, uint32(0)) == CANONICAL
    smaller = recompress_generator(encode_plain(canonical_tree()), CONSTANTS, uint32(0))
    assert smaller == CANONICAL
    assert recompress_generator(smaller, CONSTANTS, uint32(0)) == smaller


@pytest.mark.parametrize(
    "bloated",
    [
        pytest.param(CANONICAL + bytes(8), id="trailing-bytes"),
        pytest.param(encode_plain(canonical_tree()), id="no-back-refs"),
        pytest.param(encode_plain(canonical_tree(), varint_size=8), id="overlong-varints"),
    ],
)
def test_bloated_generator_shrinks(bloated: bytes) -> None:
    err, _, _ = run_block_generator2(bloated, [], CONSTANTS.MAX_BLOCK_COST_CLVM, FLAGS, G2Element(), None, CONSTANTS)
    assert err is None
    assert tree_hash_2026(bloated) == tree_hash_2026(CANONICAL)
    assert len(bloated) > len(CANONICAL)
    assert recompress_generator(bloated, CONSTANTS, uint32(0)) == CANONICAL


def test_any_tree_shrinks() -> None:
    # a generator whose outer list ends in an atom instead of nil is valid, and
    # the re-encoding keeps that tree
    generator = encode_plain(Program.to((spend_list(), b"tail")))
    err, _, _ = run_block_generator2(generator, [], CONSTANTS.MAX_BLOCK_COST_CLVM, FLAGS, G2Element(), None, CONSTANTS)
    assert err is None
    smaller = recompress_generator(generator, CONSTANTS, uint32(0))
    assert len(smaller) < len(generator)
    assert tree_hash_2026(smaller) == tree_hash_2026(generator)


def test_undecodable_keeps_original() -> None:
    generator = bytes(SERDE_2026_MAGIC_PREFIX) + b"\xff" * 20
    assert recompress_generator(generator, CONSTANTS, uint32(0)) == generator


def test_before_hard_fork2_keeps_original() -> None:
    constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(100))
    assert not get_flags_for_height_and_constants(99, constants) & INTERNED_SPEND_LIST
    bloated = CANONICAL + bytes(8)
    assert recompress_generator(bloated, constants, uint32(99)) == bloated
    assert recompress_generator(bloated, constants, uint32(100)) == CANONICAL
