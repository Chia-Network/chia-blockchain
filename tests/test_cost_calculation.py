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
        program = binutils.assemble('(q ((0x3d2331635a58c0d49912bc1427d7db51afe3f20a7b4bcaffa17ee250dcbcbfaa (((c (q ((c (q ((c (i 11 (q ((c (i (= 5 (point_add 11 (pubkey_for_exp (sha256 11 ((c 6 (c 2 (c 23 (q ()))))))))) (q ((c 23 47))) (q (x))) 1))) (q (c (c 4 (c 5 (c ((c 6 (c 2 (c 23 (q ()))))) (q ())))) ((c 23 47))))) 1))) (c (q (57 (c (i (l 5) (q (sha256 (q 2) ((c 6 (c 2 (c 9 (q ()))))) ((c 6 (c 2 (c 13 (q ()))))))) (q (sha256 (q 1) 5))) 1))) 1)))) (c (q 0x88bc9360319e7c54ab42e19e974288a2d7a817976f7633f4b43f36ce72074e59c4ab8ddac362202f3e366f0aebbb6280) 1))) (() (q ((65 "00000000000000000000000000000000" 0x0cbba106e000))) ())))))')

        error, npc_list, cost = get_name_puzzle_conditions(program, True)
        assert error is not None
        error, npc_list, cost = get_name_puzzle_conditions(program, False)
        assert error is None

        coin_name = npc_list[0].coin_name
        error, puzzle, solution = get_puzzle_and_solution_for_coin(program, coin_name)
