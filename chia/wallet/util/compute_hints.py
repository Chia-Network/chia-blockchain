from typing import List

from blspy import G2Element

from chia.types.condition_opcodes import ConditionOpcode
from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.coin_spend import CoinSpend
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.spend_bundle import SpendBundle
from chia.full_node.bundle_tools import simple_solution_generator


def compute_coin_hints(cs: CoinSpend) -> List[bytes]:

    bundle = SpendBundle([cs], G2Element())
    generator = simple_solution_generator(bundle)

    npc_result = get_name_puzzle_conditions(
        generator,
        INFINITE_COST,
        cost_per_byte=DEFAULT_CONSTANTS.COST_PER_BYTE,
        mempool_mode=False,
        height=DEFAULT_CONSTANTS.SOFT_FORK_HEIGHT,
    )
    h_list = []
    for npc in npc_result.npc_list:
        for opcode, conditions in npc.conditions:
            if opcode == ConditionOpcode.CREATE_COIN:
                for condition in conditions:
                    if len(condition.vars) > 2 and condition.vars[2] != b"":
                        h_list.append(condition.vars[2])

    return h_list
