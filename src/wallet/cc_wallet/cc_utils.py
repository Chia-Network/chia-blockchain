import dataclasses

from typing import List, Optional, Tuple

from blspy import G2Element, AugSchemeMPL

from src.types.blockchain_format.coin import Coin
from src.types.condition_opcodes import ConditionOpcode
from src.types.blockchain_format.program import Program
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.spend_bundle import CoinSolution, SpendBundle
from src.util.condition_tools import conditions_dict_for_solution
from src.util.ints import uint64
from src.wallet.puzzles.cc_loader import CC_MOD, LOCK_INNER_PUZZLE
from src.wallet.puzzles.genesis_by_coin_id_with_0 import (
    lineage_proof_for_genesis,
    lineage_proof_for_coin,
    lineage_proof_for_zero,
    genesis_coin_id_for_genesis_coin_checker,
)


NULL_SIGNATURE = G2Element.generator() * 0

ANYONE_CAN_SPEND_PUZZLE = Program.to(1)  # simply return the conditions

# information needed to spend a cc
# if we ever support more genesis conditions, like a re-issuable coin,
# we may need also to save the `genesis_coin_mod` or its hash


@dataclasses.dataclass
class SpendableCC:
    coin: Coin
    genesis_coin_id: bytes32
    inner_puzzle: Program
    lineage_proof: Program


def cc_puzzle_for_inner_puzzle(mod_code, genesis_coin_checker, inner_puzzle) -> Program:
    """
    Given an inner puzzle, generate a puzzle program for a specific cc.
    """
    return mod_code.curry(mod_code.get_tree_hash(), genesis_coin_checker, inner_puzzle)
    # return mod_code.curry([mod_code.get_tree_hash(), genesis_coin_checker, inner_puzzle])


def cc_puzzle_hash_for_inner_puzzle_hash(mod_code, genesis_coin_checker, inner_puzzle_hash) -> bytes32:
    """
    Given an inner puzzle hash, calculate a puzzle program hash for a specific cc.
    """
    gcc_hash = genesis_coin_checker.get_tree_hash()
    return mod_code.curry(mod_code.get_tree_hash(), gcc_hash, inner_puzzle_hash).get_tree_hash(
        gcc_hash, inner_puzzle_hash
    )


def lineage_proof_for_cc_parent(parent_coin: Coin, parent_inner_puzzle_hash: bytes32) -> Program:
    return Program.to(
        (
            1,
            [parent_coin.parent_coin_info, parent_inner_puzzle_hash, parent_coin.amount],
        )
    )


def subtotals_for_deltas(deltas) -> List[int]:
    """
    Given a list of deltas corresponding to input coins, create the "subtotals" list
    needed in solutions spending those coins.
    """

    subtotals = []
    subtotal = 0

    for delta in deltas:
        subtotals.append(subtotal)
        subtotal += delta

    # tweak the subtotals so the smallest value is 0
    subtotal_offset = min(subtotals)
    subtotals = [_ - subtotal_offset for _ in subtotals]
    return subtotals


def coin_solution_for_lock_coin(
    prev_coin: Coin,
    subtotal: int,
    coin: Coin,
) -> CoinSolution:
    puzzle_reveal = LOCK_INNER_PUZZLE.curry(prev_coin.as_list(), subtotal)
    coin = Coin(coin.name(), puzzle_reveal.get_tree_hash(), uint64(0))
    coin_solution = CoinSolution(coin, Program.to([puzzle_reveal, 0]))
    return coin_solution


def bundle_for_spendable_cc_list(spendable_cc: SpendableCC) -> Program:
    pair = (spendable_cc.coin.as_list(), spendable_cc.lineage_proof)
    return Program.to(pair)


def spend_bundle_for_spendable_ccs(
    mod_code: Program,
    genesis_coin_checker: Program,
    spendable_cc_list: List[SpendableCC],
    inner_solutions: List[Program],
    sigs: Optional[List[G2Element]] = [],
) -> SpendBundle:
    """
    Given a list of `SpendableCC` objects and inner solutions for those objects, create a `SpendBundle`
    that spends all those coins. Note that it the signature is not calculated it, so the caller is responsible
    for fixing it.
    """

    N = len(spendable_cc_list)

    if len(inner_solutions) != N:
        raise ValueError("spendable_cc_list and inner_solutions are different lengths")

    input_coins = [_.coin for _ in spendable_cc_list]

    # figure out what the output amounts are by running the inner puzzles & solutions
    output_amounts = []
    for cc_spend_info, inner_solution in zip(spendable_cc_list, inner_solutions):
        error, conditions, cost = conditions_dict_for_solution(Program.to([cc_spend_info.inner_puzzle, inner_solution]))
        total = 0
        if conditions:
            for _ in conditions.get(ConditionOpcode.CREATE_COIN, []):
                total += Program.to(_.vars[1]).as_int()
        output_amounts.append(total)

    coin_solutions = []

    deltas = [input_coins[_].amount - output_amounts[_] for _ in range(N)]
    subtotals = subtotals_for_deltas(deltas)

    if sum(deltas) != 0:
        raise ValueError("input and output amounts don't match")

    bundles = [bundle_for_spendable_cc_list(_) for _ in spendable_cc_list]

    for index in range(N):
        cc_spend_info = spendable_cc_list[index]

        puzzle_reveal = cc_puzzle_for_inner_puzzle(mod_code, genesis_coin_checker, cc_spend_info.inner_puzzle)

        prev_index = (index - 1) % N
        next_index = (index + 1) % N
        prev_bundle = bundles[prev_index]
        my_bundle = bundles[index]
        next_bundle = bundles[next_index]

        solution = [
            inner_solutions[index],
            prev_bundle,
            my_bundle,
            next_bundle,
            subtotals[index],
        ]
        full_solution = Program.to([puzzle_reveal, solution])

        coin_solution = CoinSolution(input_coins[index], full_solution)
        coin_solutions.append(coin_solution)

    if sigs is None or sigs == []:
        return SpendBundle(coin_solutions, NULL_SIGNATURE)
    else:
        return SpendBundle(coin_solutions, AugSchemeMPL.aggregate(sigs))


def is_cc_mod(inner_f: Program):
    """
    You may want to generalize this if different `CC_MOD` templates are supported.
    """
    return inner_f == CC_MOD


def check_is_cc_puzzle(puzzle: Program):
    r = puzzle.uncurry()
    if r is None:
        return False
    inner_f, args = r
    return is_cc_mod(inner_f)


def uncurry_cc(puzzle: Program) -> Optional[Tuple[Program, Program, Program]]:
    """
    Take a puzzle and return `None` if it's not a `CC_MOD` cc, or
    a triple of `mod_hash, genesis_coin_checker, inner_puzzle` if it is.
    """
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    if not is_cc_mod(inner_f):
        return None

    mod_hash, genesis_coin_checker, inner_puzzle = list(args.as_iter())
    return mod_hash, genesis_coin_checker, inner_puzzle


def get_lineage_proof_from_coin_and_puz(parent_coin, parent_puzzle):
    r = uncurry_cc(parent_puzzle)
    if r:
        mod_hash, genesis_checker, inner_puzzle = r
        lineage_proof = lineage_proof_for_cc_parent(parent_coin, inner_puzzle.get_tree_hash())
    else:
        if parent_coin.amount == 0:
            lineage_proof = lineage_proof_for_zero(parent_coin)
        else:
            lineage_proof = lineage_proof_for_genesis(parent_coin)
    return lineage_proof


def spendable_cc_list_from_coin_solution(coin_solution: CoinSolution, hash_to_puzzle_f) -> List[SpendableCC]:

    """
    Given a `CoinSolution`, extract out a list of `SpendableCC` objects.

    Since `SpendableCC` needs to track the inner puzzles and a `Coin` only includes
    puzzle hash, we also need a `hash_to_puzzle_f` function that turns puzzle hashes into
    the corresponding puzzles. This is generally either a `dict` or some kind of DB
    (if it's large or persistent).
    """

    spendable_cc_list = []

    coin = coin_solution.coin
    puzzle = coin_solution.solution.first()
    r = uncurry_cc(puzzle)
    if r:
        mod_hash, genesis_coin_checker, inner_puzzle = r
        lineage_proof = lineage_proof_for_cc_parent(coin, inner_puzzle.get_tree_hash())
    else:
        lineage_proof = lineage_proof_for_coin(coin)

    for new_coin in coin_solution.additions():
        puzzle = hash_to_puzzle_f(new_coin.puzzle_hash)
        if puzzle is None:
            # we don't recognize this puzzle hash, skip it
            continue
        r = uncurry_cc(puzzle)
        if r is None:
            # this isn't a cc puzzle
            continue

        mod_hash, genesis_coin_checker, inner_puzzle = r

        genesis_coin_id = genesis_coin_id_for_genesis_coin_checker(genesis_coin_checker)

        cc_spend_info = SpendableCC(new_coin, genesis_coin_id, inner_puzzle, lineage_proof)
        spendable_cc_list.append(cc_spend_info)

    return spendable_cc_list
