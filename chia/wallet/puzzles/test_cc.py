# this is used to iterate on `cc.clvm` to ensure that it's producing the sort
# of output that we expect

from typing import Dict, List, Optional, Tuple

from blspy import G2Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import CoinSolution, SpendBundle
from chia.util.ints import uint64
from chia.wallet.cc_wallet.cc_utils import (
    CC_MOD,
    cc_puzzle_for_inner_puzzle,
    cc_puzzle_hash_for_inner_puzzle_hash,
    spend_bundle_for_spendable_ccs,
    spendable_cc_list_from_coin_solution,
)
from chia.wallet.puzzles.genesis_by_coin_id_with_0 import create_genesis_or_zero_coin_checker
from chia.wallet.puzzles.genesis_by_puzzle_hash_with_0 import create_genesis_puzzle_or_zero_coin_checker

CONDITIONS = dict((k, bytes(v)[0]) for k, v in ConditionOpcode.__members__.items())  # pylint: disable=E1101

NULL_SIGNATURE = G2Element()

ANYONE_CAN_SPEND_PUZZLE = Program.to(1)  # simply return the conditions

PUZZLE_TABLE: Dict[bytes32, Program] = dict((_.get_tree_hash(), _) for _ in [ANYONE_CAN_SPEND_PUZZLE])


def hash_to_puzzle_f(puzzle_hash: bytes32) -> Optional[Program]:
    return PUZZLE_TABLE.get(puzzle_hash)


def add_puzzles_to_puzzle_preimage_db(puzzles: List[Program]) -> None:
    for _ in puzzles:
        PUZZLE_TABLE[_.get_tree_hash()] = _


def int_as_bytes32(v: int) -> bytes32:
    return v.to_bytes(32, byteorder="big")


def generate_farmed_coin(
    block_index: int,
    puzzle_hash: bytes32,
    amount: int,
) -> Coin:
    """
    Generate a (fake) coin which can be used as a starting point for a chain
    of coin tests.
    """
    return Coin(int_as_bytes32(block_index), puzzle_hash, uint64(amount))


def issue_cc_from_farmed_coin(
    mod_code: Program,
    coin_checker_for_farmed_coin,
    block_id: int,
    inner_puzzle_hash: bytes32,
    amount: int,
) -> Tuple[Program, SpendBundle]:
    """
    This is an example of how to issue a cc.
    """
    # get a farmed coin

    farmed_puzzle = ANYONE_CAN_SPEND_PUZZLE
    farmed_puzzle_hash = farmed_puzzle.get_tree_hash()

    # mint a cc

    farmed_coin = generate_farmed_coin(block_id, farmed_puzzle_hash, amount=uint64(amount))
    genesis_coin_checker = coin_checker_for_farmed_coin(farmed_coin)

    minted_cc_puzzle_hash = cc_puzzle_hash_for_inner_puzzle_hash(mod_code, genesis_coin_checker, inner_puzzle_hash)

    output_conditions = [[ConditionOpcode.CREATE_COIN, minted_cc_puzzle_hash, farmed_coin.amount]]

    # for this very simple puzzle, the solution is simply the output conditions
    # this is just a coincidence... for more complicated puzzles, you'll likely have to do some real work

    solution = Program.to(output_conditions)
    coin_solution = CoinSolution(farmed_coin, farmed_puzzle, solution)
    spend_bundle = SpendBundle([coin_solution], NULL_SIGNATURE)
    return genesis_coin_checker, spend_bundle


def solution_for_pay_to_any(puzzle_hash_amount_pairs: List[Tuple[bytes32, int]]) -> Program:
    output_conditions = [
        [ConditionOpcode.CREATE_COIN, puzzle_hash, amount] for puzzle_hash, amount in puzzle_hash_amount_pairs
    ]
    return Program.to(output_conditions)


def test_spend_through_n(mod_code, coin_checker_for_farmed_coin, n):
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
        mod_code, coin_checker_for_farmed_coin, 1, eve_inner_puzzle_hash, total_minted
    )

    # hack the wrapped puzzles into the PUZZLE_TABLE DB

    puzzles_for_db = [cc_puzzle_for_inner_puzzle(mod_code, genesis_coin_checker, eve_inner_puzzle)]
    add_puzzles_to_puzzle_preimage_db(puzzles_for_db)
    spend_bundle.debug()

    ################################

    # collect up the spendable coins

    spendable_cc_list = []
    for coin_solution in spend_bundle.coin_solutions:
        spendable_cc_list.extend(spendable_cc_list_from_coin_solution(coin_solution, hash_to_puzzle_f))

    # now spend the genesis coin cc to N outputs

    output_conditions = solution_for_pay_to_any([(eve_inner_puzzle_hash, _) for _ in output_values])
    inner_puzzle_solution = Program.to(output_conditions)

    spend_bundle = spend_bundle_for_spendable_ccs(
        mod_code,
        genesis_coin_checker,
        spendable_cc_list,
        [inner_puzzle_solution],
    )

    spend_bundle.debug()

    ################################

    # collect up the spendable coins

    spendable_cc_list = []
    for coin_solution in spend_bundle.coin_solutions:
        spendable_cc_list.extend(spendable_cc_list_from_coin_solution(coin_solution, hash_to_puzzle_f))

    # now spend N inputs to two outputs

    output_amounts = ([0] * (n - 2)) + [0x1, total_minted - 1]

    inner_solutions = [
        solution_for_pay_to_any([(eve_inner_puzzle_hash, amount)] if amount else []) for amount in output_amounts
    ]

    spend_bundle = spend_bundle_for_spendable_ccs(
        mod_code,
        genesis_coin_checker,
        spendable_cc_list,
        inner_solutions,
    )

    spend_bundle.debug()


def test_spend_zero_coin(mod_code: Program, coin_checker_for_farmed_coin):
    """
    Test to spend ccs from a farmed coin to a cc genesis coin, then to N outputs,
    then joining back down to two outputs.
    """

    eve_inner_puzzle = ANYONE_CAN_SPEND_PUZZLE
    eve_inner_puzzle_hash = eve_inner_puzzle.get_tree_hash()

    total_minted = 0x111

    genesis_coin_checker, spend_bundle = issue_cc_from_farmed_coin(
        mod_code, coin_checker_for_farmed_coin, 1, eve_inner_puzzle_hash, total_minted
    )

    puzzles_for_db = [cc_puzzle_for_inner_puzzle(mod_code, genesis_coin_checker, eve_inner_puzzle)]
    add_puzzles_to_puzzle_preimage_db(puzzles_for_db)

    eve_cc_list = []
    for _ in spend_bundle.coin_solutions:
        eve_cc_list.extend(spendable_cc_list_from_coin_solution(_, hash_to_puzzle_f))
    assert len(eve_cc_list) == 1
    eve_cc_spendable = eve_cc_list[0]

    # farm regular chia

    farmed_coin = generate_farmed_coin(2, eve_inner_puzzle_hash, amount=500)

    # create a zero cc from this farmed coin

    wrapped_cc_puzzle_hash = cc_puzzle_hash_for_inner_puzzle_hash(mod_code, genesis_coin_checker, eve_inner_puzzle_hash)

    solution = solution_for_pay_to_any([(wrapped_cc_puzzle_hash, 0)])
    coin_solution = CoinSolution(farmed_coin, ANYONE_CAN_SPEND_PUZZLE, solution)
    spendable_cc_list = spendable_cc_list_from_coin_solution(coin_solution, hash_to_puzzle_f)
    assert len(spendable_cc_list) == 1
    zero_cc_spendable = spendable_cc_list[0]

    # we have our zero coin
    # now try to spend it

    spendable_cc_list = [eve_cc_spendable, zero_cc_spendable]
    inner_solutions = [
        solution_for_pay_to_any([]),
        solution_for_pay_to_any([(wrapped_cc_puzzle_hash, eve_cc_spendable.coin.amount)]),
    ]
    spend_bundle = spend_bundle_for_spendable_ccs(mod_code, genesis_coin_checker, spendable_cc_list, inner_solutions)
    spend_bundle.debug()


def main():
    mod_code = CC_MOD

    def coin_checker_for_farmed_coin_by_coin_id(coin: Coin):
        return create_genesis_or_zero_coin_checker(coin.name())

    test_spend_through_n(mod_code, coin_checker_for_farmed_coin_by_coin_id, 12)
    test_spend_zero_coin(mod_code, coin_checker_for_farmed_coin_by_coin_id)

    def coin_checker_for_farmed_coin_by_puzzle_hash(coin: Coin):
        return create_genesis_puzzle_or_zero_coin_checker(coin.puzzle_hash)

    test_spend_through_n(mod_code, coin_checker_for_farmed_coin_by_puzzle_hash, 10)


if __name__ == "__main__":
    main()
