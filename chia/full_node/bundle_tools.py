from __future__ import annotations

from chia_rs import SpendBundle, solution_generator, solution_generator_backrefs

from chia.types.generator_types import BlockGenerator, GeneratorFormat


def simple_solution_generator(bundle: SpendBundle) -> BlockGenerator:
    spends = [(cs.coin, bytes(cs.puzzle_reveal), bytes(cs.solution)) for cs in bundle.coin_spends]
    block_program = solution_generator(spends)
    # mempool-side generation is classic-only until post-HF2 mempool emission is wired up
    return BlockGenerator(block_program, GeneratorFormat.CLASSIC, [])


def simple_solution_generator_backrefs(bundle: SpendBundle) -> BlockGenerator:
    spends = [(cs.coin, bytes(cs.puzzle_reveal), bytes(cs.solution)) for cs in bundle.coin_spends]
    block_program = solution_generator_backrefs(spends)
    # mempool-side generation is classic-only until post-HF2 mempool emission is wired up
    return BlockGenerator(block_program, GeneratorFormat.CLASSIC, [])
