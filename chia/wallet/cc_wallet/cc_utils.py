import dataclasses
from typing import List, Optional, Tuple, Iterator

from blspy import AugSchemeMPL, G2Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import CoinSpend, SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.cc_loader import CC_MOD
from chia.wallet.puzzles.genesis_by_coin_id_with_0 import genesis_coin_id_for_genesis_coin_checker

NULL_SIGNATURE = G2Element()

ANYONE_CAN_SPEND_PUZZLE = Program.to(1)  # simply return the conditions


# information needed to spend a cc
@dataclasses.dataclass
class SpendableCC:
    coin: Coin
    limitations_program: Program
    inner_puzzle: Program
    lineage_proof: Program


def match_cat_puzzle(puzzle: Program) -> Tuple[bool, Iterator[Program]]:
    """
    Given a puzzle test if it's a CAT and, if it is, return the curried arguments
    """
    mod, curried_args = puzzle.uncurry()
    if mod == CC_MOD:
        return True, curried_args.as_iter()
    else:
        return False, iter(())


def construct_cc_puzzle(mod_code: Program, genesis_coin_checker: Program, inner_puzzle: Program) -> Program:
    """
    Given an inner puzzle hash and genesis_coin_checker calculate a puzzle program for a specific cc.
    """
    return mod_code.curry(mod_code.get_tree_hash(), genesis_coin_checker.get_tree_hash(), inner_puzzle)


def get_lineage_proof_from_coin_and_puz(coin: Coin, puz: Program) -> LineageProof:
    matched, curried_args = match_cat_puzzle(puz)
    if matched:
        _, _, inner_puzzle = curried_args
        return LineageProof(coin.name(), inner_puzzle.get_tree_hash(), coin.amount)
    else:
        return LineageProof()


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


def next_info_for_spendable_cc(spendable_cc: SpendableCC) -> Program:
    c = spendable_cc.coin
    list = [c.parent_coin_info, spendable_cc.inner_puzzle.get_tree_hash(), c.amount]
    return Program.to(list)


def get_cat_truths(spendable_cc: SpendableCC, limitations_solution: Program) -> Program:
    mod_hash = CC_MOD.get_tree_hash()
    mod_hash_hash = Program.to(mod_hash).get_tree_hash()
    cc_struct = Program.to([mod_hash, mod_hash_hash, spendable_cc.limitations_program, spendable_cc.limitations_program.get_tree_hash()])
    # TRUTHS are: innerpuzhash my_amount lineage_proof CC_STRUCT my_id fullpuzhash parent_id limitations_solutions
    # CC_STRUCT is: MOD_HASH (sha256 1 MOD_HASH) limitations_program (sha256tree1 LIMITATIONS_PROGRAM_HASH)
    return Program.to(
        (
            (
                (
                    (
                        spendable_cc.inner_puzzle.get_tree_hash(),
                        [],
                    ),
                    spendable_cc.coin.amount,
                ),
                (spendable_cc.lineage_proof, cc_struct),
            ),
            (
                (spendable_cc.coin.name(), spendable_cc.coin.puzzle_hash),
                (spendable_cc.coin.parent_coin_info, limitations_solution),
            ),
        )
    )


def spend_bundle_for_spendable_ccs(
    mod_code: Program,
    genesis_coin_checker: Program,
    spendable_cc_list: List[SpendableCC],
    inner_solutions: List[Program],
    sigs: Optional[List[G2Element]] = [],
    extra_deltas: Optional[List[int]] = None,
    limitations_solutions: Optional[List[Program]] = None,
) -> SpendBundle:
    """
    Given a list of `SpendableCC` objects and inner solutions for those objects, create a `SpendBundle`
    that spends all those coins. Note that it the signature is not calculated it, so the caller is responsible
    for fixing it.
    """

    N = len(spendable_cc_list)

    if len(inner_solutions) != N:
        raise ValueError("spendable_cc_list and inner_solutions are different lengths")

    if extra_deltas is None:
        extra_deltas = [0] * len(spendable_cc_list)

    if limitations_solutions is None:
        limitations_solutions = [Program.to([])] * len(spendable_cc_list)

    input_coins = [_.coin for _ in spendable_cc_list]
    # figure out what the output amounts are by running the inner puzzles & solutions
    output_amounts = []
    for cc_spend_info, inner_solution, limitations_solution, extra_delta in zip(
        spendable_cc_list, inner_solutions, limitations_solutions, extra_deltas
    ):
        truths = get_cat_truths(cc_spend_info, limitations_solution)
        error, conditions, cost = conditions_dict_for_solution(
            cc_spend_info.inner_puzzle, truths.cons(inner_solution), INFINITE_COST
        )
        total = extra_delta * -1
        if conditions:
            for _ in conditions.get(ConditionOpcode.CREATE_COIN, []):
                total += Program.to(_.vars[1]).as_int()
        output_amounts.append(total)

    coin_spends = []

    deltas = [input_coins[_].amount - output_amounts[_] for _ in range(N)]
    subtotals = subtotals_for_deltas(deltas)

    if sum(deltas) != 0:
        raise ValueError("input and output amounts don't match")

    infos_for_next = []
    infos_for_me = []
    ids = []
    for _ in spendable_cc_list:
        infos_for_next.append(next_info_for_spendable_cc(_))
        infos_for_me.append(Program.to(_.coin.as_list()))
        ids.append(_.coin.name())

    for index in range(N):
        cc_spend_info = spendable_cc_list[index]

        puzzle_reveal = construct_cc_puzzle(mod_code, cc_spend_info.limitations_program, cc_spend_info.inner_puzzle)

        prev_index = (index - 1) % N
        next_index = (index + 1) % N
        prev_id = ids[prev_index]
        my_info = infos_for_me[index]
        next_info = infos_for_next[next_index]

        solution = [
            inner_solutions[index],
            cc_spend_info.limitations_program,  # This is a temporary hack, we are revealing the genesis checker every time!
            limitations_solutions[index],
            cc_spend_info.lineage_proof,
            prev_id,
            my_info,
            next_info,
            subtotals[index],
            extra_deltas[index],
        ]
        coin_spend = CoinSpend(input_coins[index], puzzle_reveal, Program.to(solution))
        coin_spends.append(coin_spend)

    if sigs is None or sigs == []:
        return SpendBundle(coin_spends, NULL_SIGNATURE)
    else:
        return SpendBundle(coin_spends, AugSchemeMPL.aggregate(sigs))


# We don't currently use this function, maybe we should remove it?
def spendable_cc_list_from_coin_spend(coin_spend: CoinSpend, hash_to_puzzle_f) -> List[SpendableCC]:

    """
    Given a `CoinSpend`, extract out a list of `SpendableCC` objects.

    Since `SpendableCC` needs to track the inner puzzles and a `Coin` only includes
    puzzle hash, we also need a `hash_to_puzzle_f` function that turns puzzle hashes into
    the corresponding puzzles. This is generally either a `dict` or some kind of DB
    (if it's large or persistent).
    """

    spendable_cc_list = []

    coin = coin_spend.coin
    puzzle = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
    lineage_proof = get_lineage_proof_from_coin_and_puz(coin, puzzle)

    for new_coin in coin_spend.additions():
        puzzle = hash_to_puzzle_f(new_coin.puzzle_hash)
        if puzzle is None:
            # we don't recognize this puzzle hash, skip it
            continue
        matched, curried_args = match_cat_puzzle(puzzle)
        if not matched:
            # this isn't a cc puzzle
            continue

        mod_hash, genesis_coin_checker_hash, inner_puzzle = curried_args

        genesis_coin_checker = Program.from_bytes(bytes(coin_spend.solution)).rest().first()

        cc_spend_info = SpendableCC(new_coin, genesis_coin_checker, inner_puzzle, lineage_proof.to_program())
        spendable_cc_list.append(cc_spend_info)

    return spendable_cc_list
