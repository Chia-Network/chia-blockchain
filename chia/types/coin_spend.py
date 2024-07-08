from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Union

import chia_rs

from chia.consensus.condition_costs import ConditionCost
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable

CoinSpend = chia_rs.CoinSpend


def make_spend(
    coin: Coin,
    puzzle_reveal: Union[Program, SerializedProgram],
    solution: Union[Program, SerializedProgram],
) -> CoinSpend:
    pr: SerializedProgram
    sol: SerializedProgram
    if isinstance(puzzle_reveal, SerializedProgram):
        pr = puzzle_reveal
    elif isinstance(puzzle_reveal, Program):
        pr = SerializedProgram.from_program(puzzle_reveal)
    else:
        raise ValueError("Only [SerializedProgram, Program] supported for puzzle reveal")
    if isinstance(solution, SerializedProgram):
        sol = solution
    elif isinstance(solution, Program):
        sol = SerializedProgram.from_program(solution)
    else:
        raise ValueError("Only [SerializedProgram, Program] supported for solution")

    return CoinSpend(coin, pr, sol)


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
    parent_id = cs.coin.name()
    ret: List[Coin] = []
    cost, r = cs.puzzle_reveal.run_with_cost(max_cost, cs.solution)
    for cond in Program.to(r).as_iter():
        if cost > max_cost:
            raise ValidationError(Err.BLOCK_COST_EXCEEDS_MAX, "compute_additions() for CoinSpend")
        atoms = cond.as_iter()
        op = next(atoms).atom
        if op in [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_UNSAFE,
            ConditionOpcode.AGG_SIG_ME,
        ]:
            cost += ConditionCost.AGG_SIG.value
            continue
        if op != ConditionOpcode.CREATE_COIN.value:
            continue
        cost += ConditionCost.CREATE_COIN.value
        puzzle_hash = next(atoms).as_atom()
        amount = uint64(next(atoms).as_int())
        ret.append(Coin(parent_id, puzzle_hash, uint64(amount)))

    return ret, cost


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
