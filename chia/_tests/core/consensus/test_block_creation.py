from __future__ import annotations

import pytest
from chia_rs import is_canonical_serialization, solution_generator_2026, tree_hash, tree_hash_auto
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.block_creation import compute_block_fee, generator_root
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.util.hash import std_hash


@pytest.mark.parametrize("add_amount", [[0], [1, 2, 3], []])
@pytest.mark.parametrize("rem_amount", [[0], [1, 2, 3], []])
def test_compute_block_fee(add_amount: list[int], rem_amount: list[int]) -> None:
    additions: list[Coin] = [Coin(bytes32.random(), bytes32.random(), uint64(amt)) for amt in add_amount]
    removals: list[Coin] = [Coin(bytes32.random(), bytes32.random(), uint64(amt)) for amt in rem_amount]

    # the fee is the left-overs from the removals (spent) coins after deducting
    # the newly created coins (additions)
    expected = sum(rem_amount) - sum(add_amount)

    if expected < 0:
        with pytest.raises(ValueError, match="does not fit into uint64"):
            compute_block_fee(additions, removals)
    else:
        assert compute_block_fee(additions, removals) == expected


@pytest.mark.parametrize(
    "program_bytes",
    [
        b"\x80",  # CLVM nil
        b"\xff\x01\x80",  # (1)
    ],
)
def test_generator_root_pre_hf2(program_bytes: bytes) -> None:
    constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(1000))
    assert generator_root(program_bytes, 0, constants) == std_hash(program_bytes)


@pytest.mark.parametrize(
    "program_bytes",
    [
        b"\x80",  # CLVM nil
        b"\xff\x01\x80",  # (1)
    ],
)
def test_generator_root_post_hf2(program_bytes: bytes) -> None:
    constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(0))
    expected = bytes32(tree_hash(program_bytes))
    assert generator_root(program_bytes, 0, constants) == expected
    # tree_hash_auto must agree with tree_hash for standard CLVM
    assert bytes32(tree_hash_auto(program_bytes)) == expected


def test_tree_hash_auto_matches_tree_hash_for_standard_clvm() -> None:
    programs = [b"\x80", b"\xff\x01\x80", b"\xff\x01\xff\x02\x80"]
    for prog in programs:
        assert tree_hash_auto(prog) == tree_hash(prog)


def test_is_canonical_serialization_still_rejects_pre_hf2() -> None:
    # overlong encoding of atom 0: uses 2 bytes [0x81, 0x00] instead of [0x80]
    overlong = b"\x81\x00"
    assert not is_canonical_serialization(overlong)
    # canonical nil
    assert is_canonical_serialization(b"\x80")


def test_serde_2026_generator_root_works_post_hf2() -> None:
    coin = Coin(bytes32(b"\x01" * 32), bytes32(b"\x02" * 32), uint64(100))
    puzzle = b"\x80"
    solution = b"\x80"
    serde_2026_bytes = solution_generator_2026([(coin, puzzle, solution)])

    constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(0))
    # generator_root must not raise for serde_2026 format
    result = generator_root(serde_2026_bytes, 0, constants)
    assert len(result) == 32

    # serde_2026 is NOT canonical standard CLVM
    assert not is_canonical_serialization(serde_2026_bytes)

    # but tree_hash_auto handles it
    assert bytes32(tree_hash_auto(serde_2026_bytes)) == result
