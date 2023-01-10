from __future__ import annotations

from typing import List, Set

from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode


def compute_coin_hints(cs: CoinSpend) -> List[bytes32]:
    _, result_program = cs.puzzle_reveal.run_with_cost(INFINITE_COST, cs.solution)
    h_list: List[bytes32] = []
    for condition_data in result_program.as_python():
        condition = condition_data[0]
        args = condition_data[1:]
        if condition == ConditionOpcode.CREATE_COIN and len(args) > 2:
            if isinstance(args[2], list):
                for hint in args[2]:
                    if isinstance(hint, bytes):
                        h_list.append(bytes32(hint))
    return h_list


def get_target_puzhash_from_solution(solution: Program) -> Set[bytes32]:
    if solution is None or not isinstance(solution.as_python(), list):
        return set([])
    target_puzhash = set([])
    for arg in solution.as_python():
        if isinstance(arg, list) and len(arg) == 4 and (arg[0] == b"3" or arg[0] == ConditionOpcode.CREATE_COIN):
            target_puzhash.add(bytes32(arg[1]))
        else:
            target_puzhash.update(get_target_puzhash_from_solution(Program.to(arg)))
    return target_puzhash
