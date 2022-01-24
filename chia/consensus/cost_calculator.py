from dataclasses import dataclass
from typing import List, Optional, Dict

from chia.consensus.condition_costs import ConditionCost
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.name_puzzle_condition import NPC
from chia.util.ints import uint64, uint16
from chia.util.streamable import Streamable, streamable
from chia.types.condition_with_args import ConditionWithArgs


@dataclass(frozen=True)
@streamable
class NPCResult(Streamable):
    error: Optional[uint16]
    npc_list: List[NPC]
    clvm_cost: uint64  # CLVM cost only, cost of conditions and tx size is not included


def conditions_cost(conditions: Dict[ConditionOpcode, List[ConditionWithArgs]]) -> uint64:
    total_cost = 0
    for condition, cvp_list in conditions.items():
        if condition is ConditionOpcode.AGG_SIG_UNSAFE or condition is ConditionOpcode.AGG_SIG_ME:
            total_cost += len(cvp_list) * ConditionCost.AGG_SIG.value
        elif condition is ConditionOpcode.CREATE_COIN:
            total_cost += len(cvp_list) * ConditionCost.CREATE_COIN.value
        else:
            # all other conditions are free, and we ignore unknown conditions in
            # order to allow for future soft forks
            pass
    return uint64(total_cost)


def calculate_cost_of_program(program: SerializedProgram, npc_result: NPCResult, cost_per_byte: int) -> uint64:
    """
    This function calculates the total cost of either a block or a spendbundle
    """
    total_cost = 0
    total_cost += npc_result.clvm_cost
    npc_list = npc_result.npc_list
    # Add cost of conditions
    npc: NPC
    for npc in npc_list:
        total_cost += conditions_cost(npc.condition_dict)

    # Add raw size of the program
    total_cost += len(bytes(program)) * cost_per_byte

    return uint64(total_cost)
