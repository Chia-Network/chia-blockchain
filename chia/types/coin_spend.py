from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

from chia_rs import CoinSpend

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.util.streamable import Streamable, streamable


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
        pr = puzzle_reveal.to_serialized()
    else:
        raise ValueError("Only [SerializedProgram, Program] supported for puzzle reveal")
    if isinstance(solution, SerializedProgram):
        sol = solution
    elif isinstance(solution, Program):
        sol = solution.to_serialized()
    else:
        raise ValueError("Only [SerializedProgram, Program] supported for solution")

    return CoinSpend(coin, pr, sol)


@streamable
@dataclass(frozen=True)
class SpendInfo(Streamable):
    puzzle: SerializedProgram
    solution: SerializedProgram


@dataclass(frozen=True)
class CoinSpendWithConditions:
    coin_spend: CoinSpend
    conditions: list[ConditionWithArgs]

    @staticmethod
    def from_json_dict(dict: dict[str, Any]) -> CoinSpendWithConditions:
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
