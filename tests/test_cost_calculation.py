import asyncio

import pytest

from src.full_node.bundle_tools import best_solution_program
from src.full_node.cost_calculator import calculate_cost_of_program
from src.full_node.mempool_check_conditions import get_name_puzzle_conditions, get_puzzle_and_solution_for_coin
from tests.setup_nodes import test_constants, bt
from clvm_tools import binutils

BURN_PUZZLE_HASH = b"0" * 32


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestCostCalculation:
    @pytest.mark.asyncio
    async def test_basics(self):
        wallet_tool = bt.get_pool_wallet_tool()

        num_blocks = 2
        blocks = bt.get_consecutive_blocks(
            test_constants,
            num_blocks,
            [],
            10,
        )

        spend_bundle = wallet_tool.generate_signed_transaction(
            blocks[1].get_coinbase().amount,
            BURN_PUZZLE_HASH,
            blocks[1].get_coinbase(),
        )
        assert spend_bundle is not None
        program = best_solution_program(spend_bundle)

        ratio = test_constants.CLVM_COST_RATIO_CONSTANT

        error, npc_list, clvm_cost = calculate_cost_of_program(program, ratio)

        error, npc_list, cost = get_name_puzzle_conditions(program, False)
        coin_name = npc_list[0].coin_name
        error, puzzle, solution = get_puzzle_and_solution_for_coin(program, coin_name)

        # Create condition + agg_sig_condition + length + cpu_cost
        assert (
            clvm_cost == 200 * ratio + 20 * ratio + len(bytes(program)) * ratio + cost
        )

    @pytest.mark.asyncio
    async def test_strict_mode(self):
        program = best_solution_program(spend_bundle)

        ratio = test_constants.CLVM_COST_RATIO_CONSTANT

        error, npc_list, clvm_cost = calculate_cost_of_program(program, ratio)

        error, npc_list, cost = get_name_puzzle_conditions(program, False)
        coin_name = npc_list[0].coin_name
        error, puzzle, solution = get_puzzle_and_solution_for_coin(program, coin_name)

        # Create condition + agg_sig_condition + length + cpu_cost
        assert (
            clvm_cost == 200 * ratio + 20 * ratio + len(bytes(program)) * ratio + cost
        )
