from __future__ import annotations

from chia_rs import (
    INTERNED_SPEND_LIST,
    ConsensusConstants,
    SpendBundle,
    get_flags_for_height_and_constants,
    reencode_2026,
    solution_generator,
    solution_generator_2026,
    solution_generator_backrefs,
)
from chia_rs.sized_ints import uint32

from chia.types.generator_types import BlockGenerator


def simple_solution_generator(bundle: SpendBundle, flags: int = 0) -> BlockGenerator:
    spends = [(cs.coin, bytes(cs.puzzle_reveal), bytes(cs.solution)) for cs in bundle.coin_spends]
    # once INTERNED_SPEND_LIST is active, the generator must be a serde_2026
    # serialized spend list
    if flags & INTERNED_SPEND_LIST:
        return BlockGenerator(solution_generator_2026(spends), [])
    block_program = solution_generator(spends)
    return BlockGenerator(block_program, [])


def simple_solution_generator_backrefs(bundle: SpendBundle, flags: int = 0) -> BlockGenerator:
    spends = [(cs.coin, bytes(cs.puzzle_reveal), bytes(cs.solution)) for cs in bundle.coin_spends]
    # once INTERNED_SPEND_LIST is active, the generator must be a serde_2026
    # serialized spend list
    if flags & INTERNED_SPEND_LIST:
        return BlockGenerator(solution_generator_2026(spends), [])
    block_program = solution_generator_backrefs(spends)
    return BlockGenerator(block_program, [])


def recompress_generator(generator: bytes, constants: ConsensusConstants, pre_sp_tx_height: uint32) -> bytes:
    """
    Re-encode a valid serde_2026 generator and return whichever encoding is
    smaller. After hard fork 2 the block commits to the tree hash of the
    generator, not its bytes, so any encoding of the same tree is
    interchangeable. Generators without INTERNED_SPEND_LIST are returned as-is.
    """
    flags = get_flags_for_height_and_constants(pre_sp_tx_height, constants)
    if not flags & INTERNED_SPEND_LIST:
        return generator
    try:
        reencoded = reencode_2026(generator)
    except ValueError:
        return generator
    # the re-encoding has the same tree, but it can be longer than the original
    return reencoded if len(reencoded) < len(generator) else generator
