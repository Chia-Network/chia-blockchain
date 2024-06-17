from __future__ import annotations

from chia.consensus.cost_calculator import NPCResult
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64


def cost_of_spend_bundle(spend_bundle: SpendBundle) -> int:
    program: BlockGenerator = simple_solution_generator(spend_bundle)
    # always use the post soft-fork2 semantics
    npc_result: NPCResult = get_name_puzzle_conditions(
        program,
        INFINITE_COST,
        mempool_mode=True,
        height=DEFAULT_CONSTANTS.HARD_FORK_HEIGHT,
        constants=DEFAULT_CONSTANTS,
    )
    return uint64(0 if npc_result.conds is None else npc_result.conds.cost)
