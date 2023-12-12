from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from chia_rs import (
    AGG_SIG_ARGS,
    ALLOW_BACKREFS,
    ENABLE_ASSERT_BEFORE,
    ENABLE_BLS_OPS,
    ENABLE_BLS_OPS_OUTSIDE_GUARD,
    ENABLE_FIXED_DIV,
    ENABLE_SECP_OPS,
    ENABLE_SOFTFORK_CONDITION,
    LIMIT_ANNOUNCES,
    LIMIT_OBJECTS,
    run_puzzle,
)

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class CoinSpend(Streamable):
    """
    This is a rather disparate data structure that validates coin transfers. It's generally populated
    with data from different sources, since burned coins are identified by name, so it is built up
    more often that it is streamed.
    """

    coin: Coin
    puzzle_reveal: SerializedProgram
    solution: SerializedProgram


def compute_additions_with_cost(
    cs: CoinSpend,
    *,
    max_cost: int = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
) -> Tuple[List[Coin], int]:
    """
    Run the puzzle in the specified CoinSpend and return the cost and list of
    coins created by the puzzle, i.e. additions. If the cost (CLVM- and
    condition cost) exceeds the specified max_cost, the function fails with a
    ValidationError exception. Byte cost is not included since at this point the
    puzzle and solution may have been decompressed, the true byte-cost can only be
    measured at the block generator level.
    """
    flags = (
        ENABLE_ASSERT_BEFORE
        | LIMIT_ANNOUNCES
        | LIMIT_OBJECTS
        | ENABLE_BLS_OPS
        | ENABLE_SECP_OPS
        | ENABLE_SOFTFORK_CONDITION
        | ENABLE_BLS_OPS_OUTSIDE_GUARD
        | ENABLE_FIXED_DIV
        | AGG_SIG_ARGS
        | ALLOW_BACKREFS
    )
    parent_id = cs.coin.name()
    ret: List[Coin] = []
    conditions = run_puzzle(
        bytes(cs.puzzle_reveal), bytes(cs.solution), cs.coin.parent_coin_info, cs.coin.amount, max_cost, flags
    )
    assert len(conditions.spends) == 1
    for create_coin in conditions.spends[0].create_coin:
        coin = Coin(parent_id, create_coin[0], create_coin[1])
        ret.append(coin)
    return ret, conditions.cost


def compute_additions(cs: CoinSpend, *, max_cost: int = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM) -> List[Coin]:
    return compute_additions_with_cost(cs, max_cost=max_cost)[0]


@streamable
@dataclass(frozen=True)
class SpendInfo(Streamable):
    puzzle: SerializedProgram
    solution: SerializedProgram


@dataclass(frozen=True)
class CoinSpendWithConditions:
    coin_spend: CoinSpend
    conditions: List[ConditionWithArgs]

    @staticmethod
    def from_json_dict(dict: Dict[str, Any]) -> CoinSpendWithConditions:
        return CoinSpendWithConditions(
            CoinSpend.from_json_dict(dict["coin_spend"]),
            [
                ConditionWithArgs(
                    ConditionOpcode(bytes.fromhex(condition["opcode"][2:])),
                    [bytes.fromhex(var) for var in condition["vars"]],
                )
                for condition in dict["conditions"]
            ],
        )
