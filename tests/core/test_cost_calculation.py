import asyncio
import time
import logging

import pytest

from src.consensus.cost_calculator import calculate_cost_of_program, CostResult
from src.full_node.bundle_tools import best_solution_program
from src.full_node.mempool_check_conditions import (
    get_name_puzzle_conditions,
    get_puzzle_and_solution_for_coin,
)
from src.types.blockchain_format.program import SerializedProgram
from src.util.byte_types import hexstr_to_bytes
from tests.setup_nodes import test_constants, bt
from clvm_tools import binutils

BURN_PUZZLE_HASH = b"0" * 32

log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


@pytest.fixture(scope="module")
def large_txn_hex():
    import pathlib

    my_dir = pathlib.Path(__file__).absolute().parent
    with open(my_dir / "large-block.hex", "r") as f:
        hex_str = f.read()
        yield hex_str


class TestCostCalculation:
    @pytest.mark.asyncio
    async def test_basics(self):
        wallet_tool = bt.get_pool_wallet_tool()
        ph = wallet_tool.get_new_puzzlehash()
        num_blocks = 3
        blocks = bt.get_consecutive_blocks(
            num_blocks, [], guarantee_transaction_block=True, pool_reward_puzzle_hash=ph, farmer_reward_puzzle_hash=ph
        )
        coinbase = None
        for coin in blocks[2].get_included_reward_coins():
            if coin.puzzle_hash == ph:
                coinbase = coin
                break
        assert coinbase is not None
        spend_bundle = wallet_tool.generate_signed_transaction(
            coinbase.amount,
            BURN_PUZZLE_HASH,
            coinbase,
        )
        assert spend_bundle is not None
        program = best_solution_program(spend_bundle)

        ratio = test_constants.CLVM_COST_RATIO_CONSTANT

        result: CostResult = calculate_cost_of_program(program, ratio)
        clvm_cost = result.cost

        error, npc_list, cost = get_name_puzzle_conditions(program, False)
        assert error is None
        coin_name = npc_list[0].coin_name
        error, puzzle, solution = get_puzzle_and_solution_for_coin(program, coin_name)
        assert error is None

        # Create condition + agg_sig_condition + length + cpu_cost
        assert clvm_cost == 200 * ratio + 20 * ratio + len(bytes(program)) * ratio + cost

    @pytest.mark.asyncio
    async def test_strict_mode(self):
        wallet_tool = bt.get_pool_wallet_tool()
        ph = wallet_tool.get_new_puzzlehash()

        num_blocks = 3
        blocks = bt.get_consecutive_blocks(
            num_blocks, [], guarantee_transaction_block=True, pool_reward_puzzle_hash=ph, farmer_reward_puzzle_hash=ph
        )

        coinbase = None
        for coin in blocks[2].get_included_reward_coins():
            if coin.puzzle_hash == ph:
                coinbase = coin
                break
        assert coinbase is not None
        spend_bundle = wallet_tool.generate_signed_transaction(
            coinbase.amount,
            BURN_PUZZLE_HASH,
            coinbase,
        )
        assert spend_bundle is not None
        program = SerializedProgram.from_bytes(
            binutils.assemble(
                "(q . ((0x3d2331635a58c0d49912bc1427d7db51afe3f20a7b4bcaffa17ee250dcbcbfaa"
                " (((c (q . ((c (q . ((c (i 11 (q . ((c (i (= 5 (point_add 11"
                " (pubkey_for_exp (sha256 11 ((c 6 (c 2 (c 23 (q . ())))))))))"
                " (q . ((c 23 47))) (q . (x))) 1))) (q . (c (c 4 (c 5 (c ((c 6 (c 2"
                " (c 23 (q . ()))))) (q . ())))) ((c 23 47))))) 1))) (c (q . (57 (c"
                " (i (l 5) (q . (sha256 (q . 2) ((c 6 (c 2 (c 9 (q . ()))))) ((c 6 (c"
                " 2 (c 13 (q . ()))))))) (q . (sha256 (q . 1) 5))) 1))) 1)))) (c"
                " (q . 0x88bc9360319e7c54ab42e19e974288a2d7a817976f7633f4b43"
                "f36ce72074e59c4ab8ddac362202f3e366f0aebbb6280)"
                ' 1))) (() (q . ((65 "00000000000000000000000000000000" 0x0cbba106e000))) ())))))'
            ).as_bin()
        )
        error, npc_list, cost = get_name_puzzle_conditions(program, True)
        assert error is not None
        error, npc_list, cost = get_name_puzzle_conditions(program, False)
        assert error is None

        coin_name = npc_list[0].coin_name
        error, puzzle, solution = get_puzzle_and_solution_for_coin(program, coin_name)
        assert error is None

    @pytest.mark.asyncio
    async def test_clvm_strict_mode(self):
        program = SerializedProgram.from_bytes(
            # this is a valid generator program except the first clvm
            # if-condition, that depends on executing an unknown operator
            # ("0xfe"). In strict mode, this should fail, but in non-strict
            # mode, the unknown operator should be treated as if it returns ().
            binutils.assemble(
                "(i (a (q . 0xfe) (q . ())) (q . ()) "
                "(q . ((0x3d2331635a58c0d49912bc1427d7db51afe3f20a7b4bcaffa17ee250dcbcbfaa"
                " (((c (q . ((c (q . ((c (i 11 (q . ((c (i (= 5 (point_add 11"
                " (pubkey_for_exp (sha256 11 ((c 6 (c 2 (c 23 (q . ())))))))))"
                " (q . ((c 23 47))) (q . (x))) 1))) (q . (c (c 4 (c 5 (c ((c 6 (c 2"
                " (c 23 (q . ()))))) (q . ())))) ((c 23 47))))) 1))) (c (q . (57 (c"
                " (i (l 5) (q . (sha256 (q . 2) ((c 6 (c 2 (c 9 (q . ()))))) ((c 6 (c"
                " 2 (c 13 (q . ()))))))) (q . (sha256 (q . 1) 5))) 1))) 1)))) (c"
                " (q . 0x88bc9360319e7c54ab42e19e974288a2d7a817976f7633f4b43"
                "f36ce72074e59c4ab8ddac362202f3e366f0aebbb6280)"
                ' 1))) (() (q . ((51 "00000000000000000000000000000000" 0x0cbba106e000))) ())))))'
                ")"
            ).as_bin()
        )
        error, npc_list, cost = get_name_puzzle_conditions(program, True)
        assert error is not None
        error, npc_list, cost = get_name_puzzle_conditions(program, False)
        assert error is None

    @pytest.mark.asyncio
    async def test_tx_generator_speed(self, large_txn_hex):
        generator = hexstr_to_bytes(large_txn_hex)
        program = SerializedProgram.from_bytes(generator)

        start_time = time.time()
        err, npc, cost = get_name_puzzle_conditions(program, False)
        end_time = time.time()
        duration = end_time - start_time
        assert err is None
        assert len(npc) == 687
        log.info(f"Time spent: {duration}")

        assert duration < 3

    @pytest.mark.asyncio
    async def test_standard_tx(self):

        puzzle = "((c (q . ((c (q . ((c (i 11 (q . ((c (i (= 5 (point_add 11 (pubkey_for_exp (sha256 11 ((c 6 (c 2 (c 23 (q . ()))))))))) (q . ((c 23 47))) (q . (x))) 1))) (q . (c (c 4 (c 5 (c ((c 6 (c 2 (c 23 (q . ()))))) (q . ())))) ((c 23 47))))) 1))) (c (q . (57 (c (i (l 5) (q . (sha256 (q . 2) ((c 6 (c 2 (c 9 (q . ()))))) ((c 6 (c 2 (c 13 (q . ()))))))) (q . (sha256 (q . 1) 5))) 1))) 1)))) (c (q . 0xaf949b78fa6a957602c3593a3d6cb7711e08720415dad831ab18adacaa9b27ec3dda508ee32e24bc811c0abc5781ae21) 1)))"  # noqa: E501

        solution = "(() (q . ((51 0x699eca24f2b6f4b25b16f7a418d0dc4fc5fce3b9145aecdda184158927738e3e 10) (51 0x847bb2385534070c39a39cc5dfdc7b35e2db472dc0ab10ab4dec157a2178adbf 0x00cbba106df6))) ())"  # noqa: E501
        time_start = time.time()
        total_cost = 0
        puzzle_program = SerializedProgram.from_bytes(binutils.assemble(puzzle).as_bin())
        solution_program = SerializedProgram.from_bytes(binutils.assemble(solution).as_bin())
        for i in range(0, 1000):
            cost, result = puzzle_program.run_with_cost(solution_program)
            total_cost += cost

        time_end = time.time()
        duration = time_end - time_start

        log.info(f"Time spent: {duration}")
        assert duration < 3
