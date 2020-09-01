import dataclasses

from typing import Any, List, Optional, Tuple

from blspy import G2Element, AugSchemeMPL

from clvm_tools.curry import curry as ct_curry, uncurry

from src.types.coin import Coin
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import CoinSolution, SpendBundle
from src.util.condition_tools import conditions_dict_for_solution
from src.util.ints import uint64
from src.wallet.puzzles.load_clvm import load_clvm


NULL_SIGNATURE = G2Element.generator() * 0

LOCK_INNER_PUZZLE = Program.from_bytes(bytes.fromhex("ff01ff8080"))  # (q ())

CC_MOD = load_clvm("cc.clvm", package_or_requirement=__name__)

ZERO_GENESIS_MOD = load_clvm("zero-genesis.clvm", package_or_requirement=__name__)

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


def curry(*args, **kwargs):
    """
    The clvm_tools version of curry returns `cost, program` for now.
    Eventually it will just return `program`. This placeholder awaits that day.
    """
    cost, prog = ct_curry(*args, **kwargs)
    return Program.to(prog)


def cc_puzzle_for_inner_puzzle(mod_code, genesis_coin_checker, inner_puzzle) -> Program:
    """
    Given an inner puzzle, generate a puzzle program for a specific cc.
    """
    return curry(
        mod_code, [mod_code.get_tree_hash(), genesis_coin_checker, inner_puzzle]
    )


def cc_puzzle_hash_for_inner_puzzle_hash(
    mod_code, genesis_coin_checker, inner_puzzle_hash
) -> bytes32:
    """
    Given an inner puzzle hash, calculate a puzzle program hash for a specific cc.
    """
    return curry(
        mod_code, [mod_code.get_tree_hash(), genesis_coin_checker, inner_puzzle_hash]
    ).get_tree_hash(inner_puzzle_hash)


def create_genesis_or_zero_coin_checker(genesis_coin_id: bytes32) -> Program:
    """
    Given a specific genesis coin id, create a `genesis_coin_mod` that allows
    both that coin id to issue a cc, or anyone to create a cc with amount 0.
    """
    genesis_coin_mod = ZERO_GENESIS_MOD
    return curry(genesis_coin_mod, [genesis_coin_id])


def genesis_coin_id_for_genesis_coin_checker(
    genesis_coin_checker: Program,
) -> Optional[bytes32]:
    """
    Given a `genesis_coin_checker` program, pull out the genesis coin id.
    """
    r = uncurry(genesis_coin_checker)
    if r is None:
        return r
    f, args = r
    return args.first()


def coin_as_list(coin: Coin) -> List[Any]:
    """
    Convenience function for when putting `coin_info` into a solution.
    """
    return [coin.parent_coin_info, coin.puzzle_hash, coin.amount]


def lineage_proof_for_genesis(parent_coin: Coin) -> Program:
    return Program.to((0, [coin_as_list(parent_coin), 0]))


def lineage_proof_for_zero(parent_coin: Coin) -> Program:
    return Program.to((0, [coin_as_list(parent_coin), 1]))


def lineage_proof_for_cc_parent(
    parent_coin: Coin, parent_inner_puzzle_hash: bytes32
) -> Program:
    return Program.to(
        (
            1,
            [
                parent_coin.parent_coin_info,
                parent_inner_puzzle_hash,
                parent_coin.amount,
            ],
        )
    )


def subtotals_for_deltas(deltas) -> List[int]:
    """
    Given a list of deltas corresponding to input coins, create the "subtotals" list
    needed in solutions spending those coins.
    """

    # move the first element to the end
    deltas = deltas[1:] + deltas[:1]

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
    parent_coin: Coin, next_coin: Coin, total_output_amount: int, subtotal: int
) -> CoinSolution:
    puzzle_reveal = curry(
        LOCK_INNER_PUZZLE,
        [
            total_output_amount,
            coin_as_list(parent_coin),
            coin_as_list(next_coin),
            subtotal,
        ],
    )

    coin = Coin(parent_coin.name(), puzzle_reveal.get_tree_hash(), uint64(0))
    coin_solution = CoinSolution(coin, Program.to([puzzle_reveal, 0]))
    return coin_solution


def spend_bundle_for_spendable_ccs(
    mod_code: Program,
    genesis_coin_checker: Program,
    spendable_cc_list: List[SpendableCC],
    inner_solutions: List[Program],
    sigs: Optional[List[G2Element]] = []
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
        error, conditions, cost = conditions_dict_for_solution(
            Program.to([cc_spend_info.inner_puzzle, inner_solution])
        )
        total = 0
        if conditions:
            for _ in conditions.get(ConditionOpcode.CREATE_COIN, []):
                total += Program.to(_.var2).as_int()
        output_amounts.append(total)

    coin_solutions = []

    deltas = [output_amounts[_] - input_coins[_].amount for _ in range(N)]
    subtotals = subtotals_for_deltas(deltas)

    if sum(deltas) != 0:
        raise ValueError("input and output amounts don't match")

    for index in range(N):
        cc_spend_info = spendable_cc_list[index]

        puzzle_reveal = cc_puzzle_for_inner_puzzle(
            mod_code, genesis_coin_checker, cc_spend_info.inner_puzzle
        )

        index1 = (index + 1) % N
        index2 = (index + 2) % N
        next_cc_spend_info = spendable_cc_list[index1]
        next_coin_info = coin_as_list(spendable_cc_list[index1].coin)
        coin_after_next = coin_as_list(spendable_cc_list[index2].coin)
        next_coin_output = output_amounts[index1]

        solution = [
            inner_solutions[index],
            coin_as_list(cc_spend_info.coin),
            cc_spend_info.lineage_proof,
            subtotals[index],
            next_coin_info,
            next_cc_spend_info.lineage_proof,
            next_coin_output,
            coin_after_next,
        ]
        full_solution = Program.to([puzzle_reveal, solution])

        coin_solution = CoinSolution(input_coins[index], full_solution)
        coin_solutions.append(coin_solution)

    # now add solutions to consume the lock coins

    for _ in range(N):
        index1 = (_ + 1) % N
        parent_coin = spendable_cc_list[_].coin
        next_coin = spendable_cc_list[index1].coin
        output_amount = output_amounts[_]
        subtotal = subtotals[_]
        coin_solution = coin_solution_for_lock_coin(
            parent_coin, next_coin, output_amount, subtotal
        )
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
    r = uncurry(puzzle)
    if r is None:
        return False
    inner_f, args = r
    return is_cc_mod(inner_f)


def uncurry_cc(puzzle: Program) -> Optional[Tuple[Program, Program, Program]]:
    """
    Take a puzzle and return `None` if it's not a `CC_MOD` cc, or
    a triple of `mod_hash, genesis_coin_checker, inner_puzzle` if it is.
    """
    r = uncurry(puzzle)
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


def spendable_cc_list_from_coin_solution(
    coin_solution: CoinSolution, hash_to_puzzle_f
) -> List[SpendableCC]:

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
        if coin.amount == 0:
            lineage_proof = lineage_proof_for_zero(coin)
        else:
            lineage_proof = lineage_proof_for_genesis(coin)

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

        cc_spend_info = SpendableCC(
            new_coin, genesis_coin_id, inner_puzzle, lineage_proof
        )
        spendable_cc_list.append(cc_spend_info)

    return spendable_cc_list
