from __future__ import annotations

import logging

from chia_puzzles_py.programs import CHIALISP_DESERIALISATION
from chia_rs import (
    CoinSpend,
    ConsensusConstants,
    get_flags_for_height_and_constants,
    run_chia_program,
)
from chia_rs import get_puzzle_and_solution_for_coin2 as get_puzzle_and_solution_for_coin_rust
from chia_rs.sized_ints import uint64

from chia.consensus.condition_tools import conditions_for_solution
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import CoinSpendWithConditions, SpendInfo, make_spend
from chia.types.generator_types import BlockGenerator

DESERIALIZE_MOD = Program.from_bytes(CHIALISP_DESERIALISATION)


log = logging.getLogger(__name__)


def get_puzzle_and_solution_for_coin(
    generator: BlockGenerator, coin: Coin, height: int, constants: ConsensusConstants
) -> SpendInfo:
    try:
        puzzle, solution = get_puzzle_and_solution_for_coin_rust(
            generator.program,
            generator.generator_refs,
            constants.MAX_BLOCK_COST_CLVM,
            coin,
            get_flags_for_height_and_constants(height, constants),
        )
        return SpendInfo(puzzle, solution)
    except Exception as e:
        raise ValueError(f"Failed to get puzzle and solution for coin {coin}, error: {e}") from e


def get_spends_for_block(generator: BlockGenerator, height: int, constants: ConsensusConstants) -> list[CoinSpend]:
    args = bytearray(b"\xff")
    args += bytes(DESERIALIZE_MOD)
    args += b"\xff"
    args += bytes(Program.to(generator.generator_refs))
    args += b"\x80\x80"

    _, ret = run_chia_program(
        bytes(generator.program),
        bytes(args),
        constants.MAX_BLOCK_COST_CLVM,
        get_flags_for_height_and_constants(height, constants),
    )

    spends: list[CoinSpend] = []

    for spend in Program.to(ret).first().as_iter():
        try:
            parent, puzzle, amount, solution = spend.as_iter()
            puzzle_hash = puzzle.get_tree_hash()
            coin = Coin(parent.as_atom(), puzzle_hash, uint64(amount.as_int()))
            spends.append(make_spend(coin, puzzle, solution))
        except ValueError:
            log.warning("get_spends_for_block() encountered a puzzle we couldn't serialize: {e}")

    return spends


def get_spends_for_block_with_conditions(
    generator: BlockGenerator, height: int, constants: ConsensusConstants
) -> list[CoinSpendWithConditions]:
    args = bytearray(b"\xff")
    args += bytes(DESERIALIZE_MOD)
    args += b"\xff"
    args += bytes(Program.to(generator.generator_refs))
    args += b"\x80\x80"

    flags = get_flags_for_height_and_constants(height, constants)

    _, ret = run_chia_program(
        bytes(generator.program),
        bytes(args),
        constants.MAX_BLOCK_COST_CLVM,
        flags,
    )

    spends: list[CoinSpendWithConditions] = []

    for spend in Program.to(ret).first().as_iter():
        try:
            parent, puzzle, amount, solution = spend.as_iter()
            puzzle_hash = puzzle.get_tree_hash()
            coin = Coin(parent.as_atom(), puzzle_hash, uint64(amount.as_int()))
            coin_spend = make_spend(coin, puzzle, solution)
            conditions = conditions_for_solution(puzzle, solution, constants.MAX_BLOCK_COST_CLVM)
            spends.append(CoinSpendWithConditions(coin_spend, conditions))
        except ValueError:
            log.warning("get_spends_for_block_with_conditions() encountered a puzzle we couldn't serialize: {e}")

    return spends
