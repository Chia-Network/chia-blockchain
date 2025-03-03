from __future__ import annotations

import logging
from typing import Optional

from chia_puzzles_py.programs import CHIALISP_DESERIALISATION
from chia_rs import (
    ConsensusConstants,
    get_flags_for_height_and_constants,
    run_chia_program,
)
from chia_rs import get_puzzle_and_solution_for_coin2 as get_puzzle_and_solution_for_coin_rust
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend, CoinSpendWithConditions, SpendInfo, make_spend
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util.condition_tools import conditions_for_solution
from chia.util.errors import Err

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
        parent, puzzle, amount, solution = spend.as_iter()
        puzzle_hash = puzzle.get_tree_hash()
        coin = Coin(parent.as_atom(), puzzle_hash, uint64(amount.as_int()))
        spends.append(make_spend(coin, puzzle, solution))

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
        parent, puzzle, amount, solution = spend.as_iter()
        puzzle_hash = puzzle.get_tree_hash()
        coin = Coin(parent.as_atom(), puzzle_hash, uint64(amount.as_int()))
        coin_spend = make_spend(coin, puzzle, solution)
        conditions = conditions_for_solution(puzzle, solution, constants.MAX_BLOCK_COST_CLVM)
        spends.append(CoinSpendWithConditions(coin_spend, conditions))

    return spends


def mempool_check_time_locks(
    removal_coin_records: dict[bytes32, CoinRecord],
    bundle_conds: SpendBundleConditions,
    prev_transaction_block_height: uint32,
    timestamp: uint64,
) -> Optional[Err]:
    """
    Check all time and height conditions against current state.
    """

    if prev_transaction_block_height < bundle_conds.height_absolute:
        return Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
    if timestamp < bundle_conds.seconds_absolute:
        return Err.ASSERT_SECONDS_ABSOLUTE_FAILED
    if bundle_conds.before_height_absolute is not None:
        if prev_transaction_block_height >= bundle_conds.before_height_absolute:
            return Err.ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED
    if bundle_conds.before_seconds_absolute is not None:
        if timestamp >= bundle_conds.before_seconds_absolute:
            return Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED

    for spend in bundle_conds.spends:
        unspent = removal_coin_records[bytes32(spend.coin_id)]
        if spend.birth_height is not None:
            if spend.birth_height != unspent.confirmed_block_index:
                return Err.ASSERT_MY_BIRTH_HEIGHT_FAILED
        if spend.birth_seconds is not None:
            if spend.birth_seconds != unspent.timestamp:
                return Err.ASSERT_MY_BIRTH_SECONDS_FAILED
        if spend.height_relative is not None:
            if prev_transaction_block_height < unspent.confirmed_block_index + spend.height_relative:
                return Err.ASSERT_HEIGHT_RELATIVE_FAILED
        if spend.seconds_relative is not None:
            if timestamp < unspent.timestamp + spend.seconds_relative:
                return Err.ASSERT_SECONDS_RELATIVE_FAILED
        if spend.before_height_relative is not None:
            if prev_transaction_block_height >= unspent.confirmed_block_index + spend.before_height_relative:
                return Err.ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED
        if spend.before_seconds_relative is not None:
            if timestamp >= unspent.timestamp + spend.before_seconds_relative:
                return Err.ASSERT_BEFORE_SECONDS_RELATIVE_FAILED

    return None
