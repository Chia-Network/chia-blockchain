from typing import Optional, Tuple

from clvm_tools.curry import curry, uncurry
from blspy import AugSchemeMPL
from src.types.program import Program
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.condition_opcodes import ConditionOpcode
from src.util.condition_tools import conditions_dict_for_solution
from src.wallet.puzzles.load_clvm import load_clvm


# This is for spending an existing coloured coin
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.util.ints import uint64


MOD = load_clvm("coloured_coins.clvm")
MOD_HASH = MOD.get_tree_hash()

NULL_F = Program.from_bytes(bytes.fromhex("ff01ff8080"))  # (q ())


def puzzle_for_inner_puzzle(inner_puzzle: Program, genesis_id: bytes32):
    cost, curried_mod = curry(MOD, [MOD_HASH, genesis_id, inner_puzzle])
    return Program.to(curried_mod)


def solution_parts(s: Program):
    names = "parent_info amount inner_puzzle_solution auditor_info aggees".split()
    d = dict(zip(names, s.as_iter()))
    return d


def inner_puzzle_solution(solution: Program):
    return solution_parts(solution)["inner_puzzle_solution"]


def is_ephemeral_solution(s: Program):
    return not solution_parts(s)["parent_info"].listp()


def cc_generate_eve_spend(coin: Coin, inner_puzzle: Program, genesis_id: bytes32):
    full_puzzle = puzzle_for_inner_puzzle(inner_puzzle, genesis_id)
    solution = Program.to([coin.parent_coin_info, coin.amount, 0, 0, 0])
    list_of_solutions = [CoinSolution(coin, Program.to([full_puzzle, solution]),)]
    aggsig = AugSchemeMPL.aggregate([])
    spend_bundle = SpendBundle(list_of_solutions, aggsig)
    return spend_bundle


# This is for spending a received coloured coin
def cc_make_solution(
    colour_hex: str,
    parent_info: Tuple[bytes32, bytes32, uint64],
    amount: uint64,
    inner_puzzle: Program,
    inner_solution: Program,
    auditor: Optional[Tuple[bytes32, bytes32, uint64]],
    auditees=None,
    genesis=False,
):
    # parent_info is a triplet if parent was coloured or an atom if parent was genesis coin or we're a printed 0 val
    # genesis coin isn't coloured, child of genesis uses originID, all subsequent children use triplets
    # auditor is (primary_input, innerpuzzlehash, amount)
    # aggees should be (primary_input, innerpuzhash, coin_amount, output_amount)

    #  (parent primary input, parent inner puzzle hash, parent amount)

    parent = Program.to(parent_info[0] if genesis else list(parent_info))

    auditor_list = [] if auditor is None else list(auditor)

    aggees_program = Program.to([] if auditees is None else [list(_) for _ in auditees])

    solution = Program.to(
        [parent, amount, inner_solution, auditor_list, aggees_program]
    )
    return solution


def get_uncurried_binding(puzzle: Program, idx: int) -> Optional[Program]:
    r = uncurry(puzzle)
    if r is None:
        return r
    core, bindings = r
    v = bindings
    while idx > 0:
        v = v.rest()
        idx -= 1
    v = v.first()
    return v


def get_uncurried_binding_as_atom(puzzle: Program, idx: int) -> Optional[bytes32]:
    r = get_uncurried_binding(puzzle, idx)
    if r is None:
        return r
    return r.as_atom()


def get_genesis_from_puzzle(puzzle: Program) -> bytes32:
    return get_uncurried_binding_as_atom(puzzle, 1)


def get_inner_puzzle_from_puzzle(puzzle: Program) -> bytes32:
    return get_uncurried_binding(puzzle, 2)


def get_inner_puzzle_hash_from_puzzle(puzzle: Program) -> bytes32:
    return get_inner_puzzle_from_puzzle(puzzle).get_tree_hash()


# Make sure that a generated E lock is spent in the spendbundle
def create_spend_for_ephemeral(parent_of_e, auditor_coin, spend_amount):
    cost, puzzle = curry(NULL_F, [auditor_coin.name(), spend_amount])
    puzzle = Program.to(puzzle)
    coin = Coin(parent_of_e.name(), puzzle.get_tree_hash(), uint64(0))
    solution = Program.to(0)
    coinsol = CoinSolution(coin, Program.to([puzzle, solution]))
    return coinsol


# Make sure that a generated A lock is spent in the spendbundle
def create_spend_for_auditor(parent_of_a, auditee):
    cost, puzzle = curry(NULL_F, [auditee.name()])
    puzzle = Program.to(puzzle)
    coin = Coin(parent_of_a.name(), puzzle.get_tree_hash(), uint64(0))
    solution = Program.to([])
    coinsol = CoinSolution(coin, Program.to([puzzle, solution]))
    return coinsol


# Returns the relative difference in value between the amount outputted by a puzzle and solution and a coin's amount
def get_output_discrepancy_for_puzzle_and_solution(coin, puzzle, solution):
    discrepancy = coin.amount - get_output_amount_for_puzzle_and_solution(
        puzzle, solution
    )
    return discrepancy

    # Returns the amount of value outputted by a puzzle and solution


def get_output_amount_for_puzzle_and_solution(puzzle, solution):
    puzzle_solution = puzzle.to([puzzle, solution])

    error, conditions, cost = conditions_dict_for_solution(puzzle_solution)
    if conditions is None:
        return 0

    creations = conditions.get(ConditionOpcode.CREATE_COIN)
    amount = 0
    for create_coin in creations:
        amount += Program.to(create_coin.var2).as_int()
    return amount


# inspect puzzle and check it is a CC puzzle
def check_is_cc_puzzle(puzzle: Program):
    r = uncurry(puzzle)
    if r is None:
        return False
    core, bindings = r
    return core.get_tree_hash() == MOD_HASH


def update_auditors_in_solution(solution: Program, auditor_info):
    puzzle, solution_to_puzzle = list(solution.as_iter())
    solution_entries = list(solution_to_puzzle.as_iter())
    if len(solution_entries) >= 4:
        solution_entries[3] = list(auditor_info)
    ns = Program.to([puzzle, solution_entries])
    return ns
