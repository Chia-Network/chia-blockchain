import dataclasses
from typing import List, Tuple, Iterator

from blspy import G2Element

from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import CoinSpend, SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.cat_loader import CAT_MOD

NULL_SIGNATURE = G2Element()

ANYONE_CAN_SPEND_PUZZLE = Program.to(1)  # simply return the conditions


# information needed to spend a cc
@dataclasses.dataclass
class SpendableCAT:
    coin: Coin
    limitations_program_hash: bytes32
    inner_puzzle: Program
    inner_solution: Program
    limitations_solution: Program = Program.to([])
    lineage_proof: LineageProof = LineageProof()
    extra_delta: int = 0
    limitations_program_reveal: Program = Program.to([])


def match_cat_puzzle(puzzle: Program) -> Tuple[bool, Iterator[Program]]:
    """
    Given a puzzle test if it's a CAT and, if it is, return the curried arguments
    """
    mod, curried_args = puzzle.uncurry()
    if mod == CAT_MOD:
        return True, curried_args.as_iter()
    else:
        return False, iter(())


def get_innerpuzzle_from_puzzle(puzzle: Program) -> Program:
    mod, curried_args = puzzle.uncurry()
    if mod == CAT_MOD:
        return curried_args.rest().rest().first()
    else:
        raise ValueError("Not a CAT puzzle")


def construct_cat_puzzle(mod_code: Program, limitations_program_hash: bytes32, inner_puzzle: Program) -> Program:
    """
    Given an inner puzzle hash and tail hash calculate a puzzle program for a specific cc.
    """
    return mod_code.curry(mod_code.get_tree_hash(), limitations_program_hash, inner_puzzle)


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


def next_info_for_spendable_cat(spendable_cat: SpendableCAT) -> Program:
    c = spendable_cat.coin
    list = [c.parent_coin_info, spendable_cat.inner_puzzle.get_tree_hash(), c.amount]
    return Program.to(list)


# This should probably return UnsignedSpendBundle if that type ever exists
def unsigned_spend_bundle_for_spendable_cats(mod_code: Program, spendable_cat_list: List[SpendableCAT]) -> SpendBundle:
    """
    Given a list of `SpendableCAT` objects, create a `SpendBundle` that spends all those coins.
    Note that no signing is done here, so it falls on the caller to sign the resultant bundle.
    """

    N = len(spendable_cat_list)

    # figure out what the deltas are by running the inner puzzles & solutions
    deltas = []
    for spend_info in spendable_cat_list:
        error, conditions, cost = conditions_dict_for_solution(
            spend_info.inner_puzzle, spend_info.inner_solution, INFINITE_COST
        )
        total = spend_info.extra_delta * -1
        if conditions:
            for _ in conditions.get(ConditionOpcode.CREATE_COIN, []):
                if _.vars[1] != b"\x8f":  # -113 in bytes
                    total += Program.to(_.vars[1]).as_int()
        deltas.append(spend_info.coin.amount - total)

    if sum(deltas) != 0:
        raise ValueError("input and output amounts don't match")

    subtotals = subtotals_for_deltas(deltas)

    infos_for_next = []
    infos_for_me = []
    ids = []
    for _ in spendable_cat_list:
        infos_for_next.append(next_info_for_spendable_cat(_))
        infos_for_me.append(Program.to(coin_as_list(_.coin)))
        ids.append(_.coin.name())

    coin_spends = []
    for index in range(N):
        spend_info = spendable_cat_list[index]

        puzzle_reveal = construct_cat_puzzle(mod_code, spend_info.limitations_program_hash, spend_info.inner_puzzle)

        prev_index = (index - 1) % N
        next_index = (index + 1) % N
        prev_id = ids[prev_index]
        my_info = infos_for_me[index]
        next_info = infos_for_next[next_index]

        solution = [
            spend_info.inner_solution,
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
