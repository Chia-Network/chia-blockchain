import dataclasses
from typing import List, Tuple, Iterator

from blspy import G2Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import CoinSpend, SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.cc_loader import CC_MOD

NULL_SIGNATURE = G2Element()

ANYONE_CAN_SPEND_PUZZLE = Program.to(1)  # simply return the conditions


# information needed to spend a cc
@dataclasses.dataclass
class SpendableCC:
    coin: Coin
    limitations_program: Program
    inner_puzzle: Program
    inner_solution: Program
    limitations_solution: Program = Program.to([])
    lineage_proof: LineageProof = LineageProof()
    extra_delta: int = 0
    reveal_limitations_program: bool = False


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


def get_cat_truths(spendable_cc: SpendableCC) -> Program:
    mod_hash = CC_MOD.get_tree_hash()
    mod_hash_hash = Program.to(mod_hash).get_tree_hash()
    cc_struct = Program.to(
        [mod_hash, mod_hash_hash, spendable_cc.limitations_program, spendable_cc.limitations_program.get_tree_hash()]
    )
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
                (spendable_cc.lineage_proof.to_program(), cc_struct),
            ),
            (
                (spendable_cc.coin.name(), spendable_cc.coin.puzzle_hash),
                (spendable_cc.coin.parent_coin_info, spendable_cc.limitations_solution),
            ),
        )
    )


# This should probably return UnsignedSpendBundle if that type ever exists
def unsigned_spend_bundle_for_spendable_ccs(mod_code: Program, spendable_cc_list: List[SpendableCC]) -> SpendBundle:
    """
    Given a list of `SpendableCC` objects, create a `SpendBundle` that spends all those coins.
    Note that no signing is done here, so it falls on the caller to sign the resultant bundle.
    """

    N = len(spendable_cc_list)

    # figure out what the deltas are by running the inner puzzles & solutions
    deltas = []
    for spend_info in spendable_cc_list:
        truths = get_cat_truths(spend_info)
        error, conditions, cost = conditions_dict_for_solution(
            spend_info.inner_puzzle, truths.cons(spend_info.inner_solution), INFINITE_COST
        )
        total = spend_info.extra_delta * -1
        if conditions:
            for _ in conditions.get(ConditionOpcode.CREATE_COIN, []):
                total += Program.to(_.vars[1]).as_int()
        deltas.append(spend_info.coin.amount - total)

    if sum(deltas) != 0:
        raise ValueError("input and output amounts don't match")

    subtotals = subtotals_for_deltas(deltas)

    infos_for_next = []
    infos_for_me = []
    ids = []
    for _ in spendable_cc_list:
        infos_for_next.append(next_info_for_spendable_cc(_))
        infos_for_me.append(Program.to(_.coin.as_list()))
        ids.append(_.coin.name())

    coin_spends = []
    for index in range(N):
        spend_info = spendable_cc_list[index]

        puzzle_reveal = construct_cc_puzzle(mod_code, spend_info.limitations_program, spend_info.inner_puzzle)

        prev_index = (index - 1) % N
        next_index = (index + 1) % N
        prev_id = ids[prev_index]
        my_info = infos_for_me[index]
        next_info = infos_for_next[next_index]

        limitations_reveal = spend_info.limitations_program if spend_info.reveal_limitations_program else Program.to([])
        solution = [
            spend_info.inner_solution,
            limitations_reveal,
            spend_info.limitations_solution,
            spend_info.lineage_proof.to_program(),
            prev_id,
            my_info,
            next_info,
            subtotals[index],
            spend_info.extra_delta,
        ]
        coin_spend = CoinSpend(spend_info.coin, puzzle_reveal, Program.to(solution))
        coin_spends.append(coin_spend)

    return SpendBundle(coin_spends, NULL_SIGNATURE)
