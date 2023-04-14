from __future__ import annotations

from typing import List

from chia.types.blockchain_format.program import INFINITE_COST
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
                if isinstance(args[2][0], bytes):
                    h_list.append(bytes32(args[2][0]))
    return h_list
