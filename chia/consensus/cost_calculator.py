from dataclasses import dataclass
from typing import List, Optional

from chia.consensus.condition_costs import ConditionCost
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.name_puzzle_condition import NPC
from chia.util.ints import uint16, uint64
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class CostResult(Streamable):
    error: Optional[uint16]
    npc_list: List[NPC]
    cost: uint64


def calculate_cost_of_program(
    program: SerializedProgram, clvm_cost_ratio_constant: int, strict_mode: bool = False
) -> CostResult:
    """
    This function calculates the total cost of either a block or a spendbundle
    """
    total_clvm_cost = 0
    error, npc_list, cost = get_name_puzzle_conditions(program, strict_mode)
    if error:
        raise Exception("get_name_puzzle_conditions raised error:" + str(error))
    total_clvm_cost += cost

    # Add cost of conditions
    npc: NPC
    total_vbyte_cost = 0
    for npc in npc_list:
        for condition, cvp_list in npc.condition_dict.items():
            if condition is ConditionOpcode.AGG_SIG or condition is ConditionOpcode.AGG_SIG_ME:
                total_vbyte_cost += len(cvp_list) * ConditionCost.AGG_SIG.value
            elif condition is ConditionOpcode.CREATE_COIN:
                total_vbyte_cost += len(cvp_list) * ConditionCost.CREATE_COIN.value
            elif condition is ConditionOpcode.ASSERT_SECONDS_NOW_EXCEEDS:
                total_vbyte_cost += len(cvp_list) * ConditionCost.ASSERT_SECONDS_NOW_EXCEEDS.value
            elif condition is ConditionOpcode.ASSERT_HEIGHT_AGE_EXCEEDS:
                total_vbyte_cost += len(cvp_list) * ConditionCost.ASSERT_HEIGHT_AGE_EXCEEDS.value
            elif condition is ConditionOpcode.ASSERT_HEIGHT_NOW_EXCEEDS:
                total_vbyte_cost += len(cvp_list) * ConditionCost.ASSERT_HEIGHT_NOW_EXCEEDS.value
            elif condition is ConditionOpcode.ASSERT_MY_COIN_ID:
                total_vbyte_cost += len(cvp_list) * ConditionCost.ASSERT_MY_COIN_ID.value
            elif condition is ConditionOpcode.RESERVE_FEE:
                total_vbyte_cost += len(cvp_list) * ConditionCost.RESERVE_FEE.value
            elif condition is ConditionOpcode.CREATE_ANNOUNCEMENT:
                total_vbyte_cost += len(cvp_list) * ConditionCost.CREATE_ANNOUNCEMENT.value
            elif condition is ConditionOpcode.ASSERT_ANNOUNCEMENT:
                total_vbyte_cost += len(cvp_list) * ConditionCost.ASSERT_ANNOUNCEMENT.value
            else:
                # We ignore unknown conditions in order to allow for future soft forks
                pass

    # Add raw size of the program
    total_vbyte_cost += len(bytes(program))

    total_clvm_cost += total_vbyte_cost * clvm_cost_ratio_constant

    return CostResult(error, npc_list, uint64(total_clvm_cost))
