from __future__ import annotations

from chia_rs import SpendBundle, solution_generator, solution_generator_backrefs

from chia.types.generator_types import BlockGenerator


def simple_solution_generator(bundle: SpendBundle) -> BlockGenerator:
    spends = [(cs.coin, bytes(cs.puzzle_reveal), bytes(cs.solution)) for cs in bundle.coin_spends]
    block_program = solution_generator(spends)
    return BlockGenerator(block_program, [])


def simple_solution_generator_backrefs(bundle: SpendBundle) -> BlockGenerator:
    spends = [(cs.coin, bytes(cs.puzzle_reveal), bytes(cs.solution)) for cs in bundle.coin_spends]
    block_program = solution_generator_backrefs(spends)
    return BlockGenerator(block_program, [])
