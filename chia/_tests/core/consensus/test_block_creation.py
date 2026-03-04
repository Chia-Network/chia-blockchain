from __future__ import annotations

from collections.abc import Sequence

import pytest
from chia_rs import (
    G1Element,
    G2Element,
    PoolTarget,
    ProofOfSpace,
    RewardChainBlockUnfinished,
    tree_hash,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint32, uint64, uint128

from chia.consensus.block_creation import compute_block_fee, create_foliage
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.generator_types import NewBlockGenerator
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


def _make_proof_of_space() -> ProofOfSpace:
    return ProofOfSpace(
        bytes32.zeros,
        G1Element(),
        None,
        G1Element(),
        uint8(0),
        uint16(0),
        uint8(0),
        uint8(0),
        uint8(20),
        bytes(32 * 5),
    )


def _make_rc_block_unfinished() -> RewardChainBlockUnfinished:
    return RewardChainBlockUnfinished(
        uint128(1),
        uint8(1),
        bytes32.zeros,
        _make_proof_of_space(),
        None,
        G2Element(),
        None,
        G2Element(),
    )


def _dummy_plot_sig(_msg: bytes32, _pk: G1Element) -> G2Element:
    return G2Element()


def _dummy_pool_sig(_target: PoolTarget, _pk: G1Element | None) -> G2Element | None:
    return G2Element()


def _zero_fees(_additions: Sequence[Coin], _removals: Sequence[Coin]) -> uint64:
    return uint64(0)


def _call_create_foliage_genesis(constants, program_bytes: bytes) -> bytes32:
    """Call create_foliage for a genesis block and return the generator_root."""
    from chia_rs import Program

    program = Program.from_bytes(program_bytes)
    gen = NewBlockGenerator(
        program=program,
        block_refs=[],
        signature=G2Element(),
        additions=[],
        removals=[],
        cost=uint64(0),
    )
    _, ftb, tx_info = create_foliage(
        constants,
        _make_rc_block_unfinished(),
        gen,
        None,  # prev_block (genesis)
        {},  # type: ignore[arg-type]
        uint128(0),
        uint64(0),
        bytes32.zeros,
        PoolTarget(bytes32.zeros, uint32(0)),
        _dummy_plot_sig,
        _dummy_pool_sig,
        b"seed",
        _zero_fees,
    )
    assert tx_info is not None
    return tx_info.generator_root


@pytest.mark.parametrize(
    "program_bytes",
    [
        b"\x80",  # CLVM nil
        b"\xff\x01\x80",  # (1)
    ],
)
def test_generator_hash_pre_hf2(program_bytes: bytes) -> None:
    constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(1000))
    generator_root = _call_create_foliage_genesis(constants, program_bytes)

    from chia_rs import Program

    expected = std_hash(Program.from_bytes(program_bytes))
    assert generator_root == expected


@pytest.mark.parametrize(
    "program_bytes",
    [
        b"\x80",  # CLVM nil
        b"\xff\x01\x80",  # (1)
    ],
)
def test_generator_hash_post_hf2(program_bytes: bytes) -> None:
    constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(0))
    generator_root = _call_create_foliage_genesis(constants, program_bytes)

    expected = bytes32(tree_hash(program_bytes))
    assert generator_root == expected


def test_generator_hash_differs_between_forks() -> None:
    program_bytes = b"\xff\x01\x80"  # (1)

    pre_constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(1000))
    post_constants = DEFAULT_CONSTANTS.replace(HARD_FORK2_HEIGHT=uint32(0))

    pre_root = _call_create_foliage_genesis(pre_constants, program_bytes)
    post_root = _call_create_foliage_genesis(post_constants, program_bytes)

    assert pre_root != post_root
