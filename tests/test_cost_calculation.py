import asyncio

import pytest

from src.consensus.constants import constants
from src.util.bundle_tools import best_solution_program
from src.util.cost_calculator import calculate_cost_of_program
from src.util.mempool_check_conditions import get_name_puzzle_conditions
from tests.setup_nodes import test_constants, bt
from tests.wallet_tools import WalletTool


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestCostCalculation:
    @pytest.mark.asyncio
    async def test_basics(self):
        wallet_tool = WalletTool()
        receiver = WalletTool()

        num_blocks = 2
        blocks = bt.get_consecutive_blocks(
            test_constants,
            num_blocks,
            [],
            10,
            reward_puzzlehash=wallet_tool.get_new_puzzlehash(),
        )

        spend_bundle = wallet_tool.generate_signed_transaction(
            blocks[1].header.data.coinbase.amount,
            receiver.get_new_puzzlehash(),
            blocks[1].header.data.coinbase,
        )
        assert spend_bundle is not None
        program = best_solution_program(spend_bundle)

        error, npc_list, clvm_cost = calculate_cost_of_program(program)

        error, npc_list, cost = get_name_puzzle_conditions(program)

        # Create condition + agg_sig_condition + length + cpu_cost
        ratio = constants["CLVM_COST_RATIO_CONSTANT"]
        assert (
            clvm_cost == 200 * ratio + 20 * ratio + len(bytes(program)) * ratio + cost
        )
