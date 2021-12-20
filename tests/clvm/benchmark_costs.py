from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.spend_bundle import SpendBundle
from chia.types.generator_types import BlockGenerator
from chia.consensus.cost_calculator import calculate_cost_of_program, NPCResult
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions


def cost_of_spend_bundle(spend_bundle: SpendBundle) -> int:
    program: BlockGenerator = simple_solution_generator(spend_bundle)
    npc_result: NPCResult = get_name_puzzle_conditions(
        program, INFINITE_COST, cost_per_byte=DEFAULT_CONSTANTS.COST_PER_BYTE, mempool_mode=True
    )
    cost: int = calculate_cost_of_program(program.program, npc_result, DEFAULT_CONSTANTS.COST_PER_BYTE)
    return cost
