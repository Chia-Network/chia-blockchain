import asyncio
import logging
import pathlib
import time

import pytest
from clvm_tools import binutils

from chia.consensus.cost_calculator import CostResult, calculate_cost_of_program
from chia.full_node.bundle_tools import best_solution_program
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions, get_puzzle_and_solution_for_coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.wallet.puzzles import p2_delegated_puzzle_or_hidden_puzzle
from tests.setup_nodes import bt, test_constants

from .make_block_generator import make_block_generator

BURN_PUZZLE_HASH = b"0" * 32
SMALL_BLOCK_GENERATOR = make_block_generator(1)

log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


def large_block_generator(size):
    # make a small block and hash it
    # use this in the name for the cached big block
    # the idea is, if the algorithm for building the big block changes,
    # the name of the cache file will also change

    name = SMALL_BLOCK_GENERATOR.get_tree_hash().hex()[:16]

    my_dir = pathlib.Path(__file__).absolute().parent
    hex_path = my_dir / f"large-block-{name}-{size}.hex"
    try:
        with open(hex_path) as f:
            hex_str = f.read()
            return bytes.fromhex(hex_str)
    except FileNotFoundError:
        generator = make_block_generator(size)
        blob = bytes(generator)
        #  TODO: Re-enable large-block*.hex but cache in ~/.chia/subdir
        #  with open(hex_path, "w") as f:
        #      f.write(blob.hex())
        return blob


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
        assert clvm_cost == 200 * ratio + 92 * ratio + len(bytes(program)) * ratio + cost

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

        pk = bytes.fromhex(
            "88bc9360319e7c54ab42e19e974288a2d7a817976f7633f4b43f36ce72074e59c4ab8ddac362202f3e366f0aebbb6280"
        )
        puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_pk(pk)
        disassembly = binutils.disassemble(puzzle)
        program = SerializedProgram.from_bytes(
            binutils.assemble(
                f"(q . (((0x3d2331635a58c0d49912bc1427d7db51afe3f20a7b4bcaffa17ee250dcbcbfaa 300)"
                f" ({disassembly} (() (q . ((65 '00000000000000000000000000000000' 0x0cbba106e000))) ())))))"
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
        block = Program.from_bytes(bytes(SMALL_BLOCK_GENERATOR))
        disassembly = binutils.disassemble(block)
        # this is a valid generator program except the first clvm
        # if-condition, that depends on executing an unknown operator
        # ("0xfe"). In strict mode, this should fail, but in non-strict
        # mode, the unknown operator should be treated as if it returns ().
        program = SerializedProgram.from_bytes(binutils.assemble(f"(i (0xfe (q . 0)) (q . ()) {disassembly})").as_bin())
        error, npc_list, cost = get_name_puzzle_conditions(program, True)
        assert error is not None
        error, npc_list, cost = get_name_puzzle_conditions(program, False)
        assert error is None

    @pytest.mark.asyncio
    async def test_tx_generator_speed(self):
        LARGE_BLOCK_COIN_CONSUMED_COUNT = 687
        generator = large_block_generator(LARGE_BLOCK_COIN_CONSUMED_COUNT)
        program = SerializedProgram.from_bytes(generator)

        start_time = time.time()
        err, npc, cost = get_name_puzzle_conditions(program, False)
        end_time = time.time()
        duration = end_time - start_time
        assert err is None
        assert len(npc) == LARGE_BLOCK_COIN_CONSUMED_COUNT
        log.info(f"Time spent: {duration}")

        assert duration < 3

    @pytest.mark.asyncio
    async def test_standard_tx(self):
        # this isn't a real public key, but we don't care
        public_key = bytes.fromhex(
            "af949b78fa6a957602c3593a3d6cb7711e08720415dad83" "1ab18adacaa9b27ec3dda508ee32e24bc811c0abc5781ae21"
        )
        puzzle_program = SerializedProgram.from_bytes(p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_pk(public_key))
        conditions = binutils.assemble(
            "((51 0x699eca24f2b6f4b25b16f7a418d0dc4fc5fce3b9145aecdda184158927738e3e 10)"
            " (51 0x847bb2385534070c39a39cc5dfdc7b35e2db472dc0ab10ab4dec157a2178adbf 0x00cbba106df6))"
        )
        solution_program = SerializedProgram.from_bytes(
            p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(conditions)
        )

        time_start = time.time()
        total_cost = 0
        for i in range(0, 1000):
            cost, result = puzzle_program.run_with_cost(solution_program)
            total_cost += cost

        time_end = time.time()
        duration = time_end - time_start

        log.info(f"Time spent: {duration}")
        assert duration < 3
