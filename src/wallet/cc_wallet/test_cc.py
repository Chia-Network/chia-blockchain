# this is used to iterate on `lock_coins.clvm` to ensure that it's producing the sort
# of output that we expect

from typing import Dict, Optional, Tuple

from blspy import G2Element

from src.types.coin import Coin
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import CoinSolution, SpendBundle
from src.util.ints import uint64
from src.wallet.puzzles.load_clvm import load_clvm
from src.wallet.cc_wallet.debug_spend_bundle import debug_spend_bundle
from src.wallet.cc_wallet.cc_utils import (
    cc_puzzle_for_inner_puzzle,
    create_genesis_or_zero_coin_checker,
    cc_puzzle_hash_for_inner_puzzle_hash,
    spendable_cc_list_from_coin_solution,
    spend_bundle_for_spendable_ccs,
)

CONDITIONS = dict((k, bytes(v)[0]) for k, v in ConditionOpcode.__members__.items())

NULL_SIGNATURE = G2Element.generator() * 0

ANYONE_CAN_SPEND_PUZZLE = Program.to(1)  # simply return the conditions

NULL_F = Program.from_bytes(bytes.fromhex("ff01ff8080"))  # (q ())

CC_MOD = load_clvm("cc.clvm", package_or_requirement=__name__)

ZERO_GENESIS_MOD = load_clvm("zero-genesis.clvm", package_or_requirement=__name__)


PUZZLE_TABLE: Dict[bytes32, Program] = dict(
    (_.get_tree_hash(), _) for _ in [ANYONE_CAN_SPEND_PUZZLE]
)


def hash_to_puzzle_f(puzzle_hash: bytes32) -> Optional[Program]:
    return PUZZLE_TABLE.get(puzzle_hash)


def int_as_bytes32(v: int) -> bytes32:
    return v.to_bytes(32, byteorder="big")


def generate_farmed_coin(
    block_index: int,
    puzzle_hash: bytes32,
    amount: uint64,
) -> Coin:
    """
    Generate a (fake) coin which can be used as a starting point for a chain
    of coin tests.
    """
    return Coin(int_as_bytes32(block_index), puzzle_hash, amount)


def issue_cc_from_farmed_coin(
    mod_code: Program, block_id: int, inner_puzzle_hash: bytes32, amount: uint64
) -> Tuple[Program, SpendBundle]:
    """
    This is an example of how to issue a cc.
    """

    # get a farmed coin

    farmed_puzzle = ANYONE_CAN_SPEND_PUZZLE
    farmed_puzzle_hash = farmed_puzzle.get_tree_hash()

    # mint a cc

    farmed_coin = generate_farmed_coin(block_id, farmed_puzzle_hash, amount=amount)
    genesis_coin_checker = create_genesis_or_zero_coin_checker(farmed_coin.name())

    minted_cc_puzzle_hash = cc_puzzle_hash_for_inner_puzzle_hash(
        mod_code, genesis_coin_checker, inner_puzzle_hash
    )

    output_conditions = [
        [ConditionOpcode.CREATE_COIN, minted_cc_puzzle_hash, farmed_coin.amount]
    ]

    # for this very simple puzzle, the solution is simply the output conditions
    # this is just a coincidence... for more complicated puzzles, you'll likely have to do some real work

    solution = Program.to(output_conditions)
    coin_solution = CoinSolution(farmed_coin, Program.to([farmed_puzzle, solution]))
    spend_bundle = SpendBundle([coin_solution], NULL_SIGNATURE)
    return genesis_coin_checker, spend_bundle


def solution_for_pay_to_any(puzzle_hash_amount_pairs: Tuple[bytes32, int]) -> Program:
    output_conditions = [
        [ConditionOpcode.CREATE_COIN, puzzle_hash, amount]
        for puzzle_hash, amount in puzzle_hash_amount_pairs
    ]
    return Program.to(output_conditions)


def test_spend_through_n(mod_code, n):
    """
    Test to spend ccs from a farmed coin to a cc genesis coin, then to N outputs,
    then joining back down to two outputs.
    """

    ################################

    # spend from a farmed coin to a cc genesis coin

    # get a farmed coin

    eve_inner_puzzle = ANYONE_CAN_SPEND_PUZZLE
    eve_inner_puzzle_hash = eve_inner_puzzle.get_tree_hash()

    # generate output values [0x100, 0x200, ...]

    output_values = [0x100 + 0x100 * _ for _ in range(n)]
    total_minted = sum(output_values)

    genesis_coin_checker, spend_bundle = issue_cc_from_farmed_coin(
        mod_code, 1, eve_inner_puzzle_hash, total_minted
    )

    # hack the wrapped puzzles into the PUZZLE_TABLE DB

    for _ in [
        cc_puzzle_for_inner_puzzle(mod_code, genesis_coin_checker, eve_inner_puzzle)
    ]:
        PUZZLE_TABLE[_.get_tree_hash()] = _

    debug_spend_bundle(spend_bundle)

    ################################

    # collect up the spendable coins

    spendable_cc_list = []
    for coin_solution in spend_bundle.coin_solutions:
        spendable_cc_list.extend(
            spendable_cc_list_from_coin_solution(coin_solution, hash_to_puzzle_f)
        )

    # now spend the genesis coin cc to N outputs

    output_conditions = solution_for_pay_to_any(
        [(eve_inner_puzzle_hash, _) for _ in output_values]
    )
    inner_puzzle_solution = Program.to(output_conditions)

    spend_bundle = spend_bundle_for_spendable_ccs(
        mod_code,
        genesis_coin_checker,
        spendable_cc_list,
        [inner_puzzle_solution],
    )

    debug_spend_bundle(spend_bundle)

    ################################

    # collect up the spendable coins

    spendable_cc_list = []
    for coin_solution in spend_bundle.coin_solutions:
        spendable_cc_list.extend(
            spendable_cc_list_from_coin_solution(coin_solution, hash_to_puzzle_f)
        )

    # now spend N inputs to two outputs

    output_amounts = ([0] * (n - 2)) + [0x1, total_minted - 1]

    inner_solutions = [
        solution_for_pay_to_any([(eve_inner_puzzle_hash, amount)] if amount else [])
        for amount in output_amounts
    ]

    spend_bundle = spend_bundle_for_spendable_ccs(
        mod_code,
        genesis_coin_checker,
        spendable_cc_list,
        inner_solutions,
    )

    debug_spend_bundle(spend_bundle)


def main():
    mod_code = CC_MOD
    test_spend_through_n(mod_code, 12)


if __name__ == "__main__":
    main()
