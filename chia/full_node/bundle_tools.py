from __future__ import annotations

from chia_rs import (
    INTERNED_SPEND_LIST,
    SpendBundle,
    solution_generator,
    solution_generator_2026,
    solution_generator_backrefs,
)

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
