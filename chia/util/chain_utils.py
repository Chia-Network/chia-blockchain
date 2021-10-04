from typing import List

from clvm.casts import int_from_bytes

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import (
    conditions_dict_for_solution,
    created_outputs_for_conditions_dict,
)


def additions_for_solution(
    coin_name: bytes32, puzzle_reveal: SerializedProgram, solution: SerializedProgram, max_cost: int
) -> List[Coin]:
    """
    Checks the conditions created by CoinSpend and returns the list of all coins created
    """
    err, dic, cost = conditions_dict_for_solution(puzzle_reveal, solution, max_cost)
    if err or dic is None:
        return []
    return created_outputs_for_conditions_dict(dic, coin_name)


def fee_for_solution(puzzle_reveal: SerializedProgram, solution: SerializedProgram, max_cost: int) -> int:
    err, dic, cost = conditions_dict_for_solution(puzzle_reveal, solution, max_cost)
    if err or dic is None:
        return 0

    total = 0
    for cvp in dic.get(ConditionOpcode.RESERVE_FEE, []):
        amount_bin = cvp.vars[0]
        amount = int_from_bytes(amount_bin)
        total += amount
    return total
