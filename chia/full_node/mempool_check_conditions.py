from __future__ import annotations

import logging
import typing

from chia_puzzles_py.programs import CHIALISP_DESERIALISATION
from chia_rs import (
    CoinSpend,
    ConsensusConstants,
    get_flags_for_height_and_constants,
    get_spends_for_trusted_block,
    get_spends_for_trusted_block_with_conditions,
)
from chia_rs import get_puzzle_and_solution_for_coin2 as get_puzzle_and_solution_for_coin_rust

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import SpendInfo
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


def get_spends_for_block(
    generator: BlockGenerator, height: int, constants: ConsensusConstants
) -> list[dict[str, list[CoinSpend]]]:
    spends = get_spends_for_trusted_block(
        constants,
        generator.program,
        generator.generator_refs,
        get_flags_for_height_and_constants(height, constants),
    )

    return spends


def get_spends_for_block_with_conditions(
    generator: BlockGenerator, height: int, constants: ConsensusConstants
) -> list[dict[str, typing.Any]]:
    spends = get_spends_for_trusted_block_with_conditions(
        constants,
        generator.program,
        generator.generator_refs,
        get_flags_for_height_and_constants(height, constants),
    )

    return spends
