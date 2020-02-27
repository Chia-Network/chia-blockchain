from src.consensus.condition_costs import ConditionCost
from src.types.condition_opcodes import ConditionOpcode
from src.types.hashable.Program import Program
from src.types.name_puzzle_condition import NPC
from src.util.ints import uint64
from src.util.mempool_check_conditions import get_name_puzzle_conditions


def calculate_cost_of_program(program: Program) -> uint64:
    """
    This function calculates the total cost of either block or a spendbundle
    """
    total_cost = 0
    error, npc_list, cost = get_name_puzzle_conditions(program)
    if error:
        raise
    total_cost += cost

    # Add cost of conditions
    npc: NPC
    for npc in npc_list:
        for condition, cvp_list in npc.condition_dict.items():
            if condition is ConditionOpcode.AGG_SIG:
                total_cost += len(cvp_list) * ConditionCost.AGG_SIG.value
            elif condition is ConditionOpcode.CREATE_COIN:
                total_cost += len(cvp_list) * ConditionCost.CREATE_COIN.value
            elif condition is ConditionOpcode.ASSERT_TIME_EXCEEDS:
                total_cost += len(cvp_list) * ConditionCost.ASSERT_TIME_EXCEEDS.value
            elif condition is ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
                total_cost += len(cvp_list) * ConditionCost.ASSERT_BLOCK_AGE_EXCEEDS.value
            elif condition is ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
                total_cost += len(cvp_list) * ConditionCost.ASSERT_BLOCK_INDEX_EXCEEDS.value
            elif condition is ConditionOpcode.ASSERT_MY_COIN_ID:
                total_cost += len(cvp_list) * ConditionCost.ASSERT_MY_COIN_ID.value
            elif condition is ConditionOpcode.ASSERT_COIN_CONSUMED:
                total_cost += len(cvp_list) * ConditionCost.ASSERT_COIN_CONSUMED.value

    # Add raw size of the program
    total_cost += len(bytes(program))

    return uint64(total_cost)
