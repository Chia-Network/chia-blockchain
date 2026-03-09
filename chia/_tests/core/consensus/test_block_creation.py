from __future__ import annotations

import pytest
from chia_rs import tree_hash
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
    assert generator_root(program_bytes, 0, constants) == bytes32(tree_hash(program_bytes))
