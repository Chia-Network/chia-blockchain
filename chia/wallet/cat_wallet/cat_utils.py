from __future__ import annotations

import dataclasses
from typing import Iterator, List, Optional

from blspy import G2Element

from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.uncurried_puzzle import UncurriedPuzzle

NULL_SIGNATURE = G2Element()

ANYONE_CAN_SPEND_PUZZLE = Program.to(1)  # simply return the conditions
CAT_MOD = load_clvm_maybe_recompile("cat_v2.clsp", package_or_requirement="chia.wallet.puzzles")
CAT_MOD_HASH = CAT_MOD.get_tree_hash()


def empty_program() -> Program:
    # ignoring hint error here for:
    # https://github.com/Chia-Network/clvm/pull/102
    # https://github.com/Chia-Network/clvm/pull/106
    return Program.to([])  # type: ignore[no-any-return]


# information needed to spend a cc
@dataclasses.dataclass
class SpendableCAT:
    coin: Coin
    limitations_program_hash: bytes32
    inner_puzzle: Program
    inner_solution: Program
    limitations_solution: Program = dataclasses.field(default_factory=empty_program)
    lineage_proof: LineageProof = LineageProof()
    extra_delta: int = 0
    limitations_program_reveal: Program = dataclasses.field(default_factory=empty_program)


def match_cat_puzzle(puzzle: UncurriedPuzzle) -> Optional[Iterator[Program]]:
    """
    Given the curried puzzle and args, test if it's a CAT and,
    if it is, return the curried arguments
    """
    if puzzle.mod == CAT_MOD:
        ret: Iterator[Program] = puzzle.args.as_iter()
        return ret
    else:
        return None


def get_innerpuzzle_from_puzzle(puzzle: Program) -> Program:
    mod, curried_args = puzzle.uncurry()
    if mod == CAT_MOD:
        return curried_args.at("rrf")
    else:
        raise ValueError("Not a CAT puzzle")


def construct_cat_puzzle(
    mod_code: Program, limitations_program_hash: bytes32, inner_puzzle: Program, mod_code_hash: Optional[bytes32] = None
) -> Program:
    """
    Given an inner puzzle hash and tail hash calculate a puzzle program for a specific cc.
    """
    if mod_code_hash is None:
        mod_code_hash = mod_code.get_tree_hash()
    return mod_code.curry(mod_code_hash, limitations_program_hash, inner_puzzle)


def subtotals_for_deltas(deltas: List[int]) -> List[int]:
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
    # ignoring hint error here for:
    # https://github.com/Chia-Network/clvm/pull/102
    return Program.to(list)  # type: ignore[no-any-return]


# This should probably return UnsignedSpendBundle if that type ever exists
def unsigned_spend_bundle_for_spendable_cats(mod_code: Program, spendable_cat_list: List[SpendableCAT]) -> SpendBundle:
    """
    Given a list of `SpendableCAT` objects, create a `SpendBundle` that spends all those coins.
    Note that no signing is done here, so it falls on the caller to sign the resultant bundle.
    """

    N = len(spendable_cat_list)

    # figure out what the deltas are by running the inner puzzles & solutions
    deltas: List[int] = []
    for spend_info in spendable_cat_list:
        conditions = conditions_dict_for_solution(spend_info.inner_puzzle, spend_info.inner_solution, INFINITE_COST)
        total = spend_info.extra_delta * -1
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
