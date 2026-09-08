from __future__ import annotations

import dataclasses
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar, cast

from chia_puzzles_py.programs import CAT_PUZZLE, CAT_PUZZLE_HASH
from chia_rs import G2Element
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program, run
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.wallet.conditions import Condition, CreateCoin, parse_conditions_non_consensus
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.puzzle_drivers import (
    InnerPuzzle,
    OuterPuzzle,
    PuzzleWithPuzzleHash,
    SmartCoin,
    Solution,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.uncurried_puzzle import UncurriedPuzzle
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash, curry_and_treehash
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

CAT_MOD = Program.from_bytes(CAT_PUZZLE)
CAT_MOD_HASH = bytes32(CAT_PUZZLE_HASH)
QUOTED_CAT_MOD_HASH = calculate_hash_of_quoted_mod_hash(CAT_MOD_HASH)
CAT_MOD_HASH_HASH: bytes32 = Program.to(CAT_MOD_HASH).get_tree_hash()


@dataclasses.dataclass(frozen=True, kw_only=True)
class CATCorePuzzles:
    cat_mod: Program = dataclasses.field(default_factory=lambda: CAT_MOD)
    cat_mod_hash_pre_computed: bytes32 | None = CAT_MOD_HASH
    hash_of_quoted_mod_hash_pre_computed: bytes32 | None = calculate_hash_of_quoted_mod_hash(CAT_MOD_HASH)

    @cached_property
    def cat_mod_hash(self) -> bytes32:
        if self.cat_mod_hash_pre_computed is not None:
            return self.cat_mod_hash_pre_computed
        else:
            return self.cat_mod.get_tree_hash()

    @cached_property
    def hash_of_quoted_mod_hash(self) -> bytes32:
        if self.hash_of_quoted_mod_hash_pre_computed is not None:
            return self.hash_of_quoted_mod_hash_pre_computed
        else:
            return calculate_hash_of_quoted_mod_hash(self.cat_mod_hash)


HASH_TREE_CAT_CORE_PUZZLES = CATCorePuzzles(
    cat_mod=Program.to(CAT_MOD_HASH),
    cat_mod_hash_pre_computed=CAT_MOD_HASH_HASH,
    hash_of_quoted_mod_hash_pre_computed=calculate_hash_of_quoted_mod_hash(CAT_MOD_HASH_HASH),
)


_T_InnerPuzzle = TypeVar("_T_InnerPuzzle", bound=InnerPuzzle)


@dataclasses.dataclass(frozen=True, kw_only=True)
class CATPuzzle(PuzzleWithPuzzleHash, Generic[_T_InnerPuzzle]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast("CATPuzzle[_T_InnerPuzzle]", None)

    tail_hash: bytes32
    inner_puzzle: _T_InnerPuzzle
    cat_puzzles: ClassVar[CATCorePuzzles] = CATCorePuzzles()

    def _inner_curry_arg(self) -> Program | bytes32:
        if isinstance(self.inner_puzzle, UnknownPuzzle) and self.inner_puzzle.known_puzzle is None:
            assert self.inner_puzzle.known_puzzle_hash is not None
            return self.inner_puzzle.known_puzzle_hash
        return self.inner_puzzle.puzzle

    @property
    def puzzle(self) -> Program:
        return self.cat_puzzles.cat_mod.curry(self.cat_puzzles.cat_mod_hash, self.tail_hash, self._inner_curry_arg())

    @cached_property
    def _pre_hashed_tail_hash(self) -> bytes32:
        return Program.to(self.tail_hash).get_tree_hash()

    @cached_property
    def _pre_hashed_cat_mod_hash(self) -> bytes32:
        return Program.to(self.cat_puzzles.cat_mod_hash).get_tree_hash()

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        # CAT is curried as: MOD.curry(MOD_HASH, tail_hash, inner_puzzle)
        return curry_and_treehash(
            self.cat_puzzles.hash_of_quoted_mod_hash,
            self._pre_hashed_cat_mod_hash,
            self._pre_hashed_tail_hash,
            self.inner_puzzle.puzzle_hash,
        )

    @classmethod
    def match_uncurried(cls, uncurried: UncurriedPuzzle) -> CATPuzzle[UnknownPuzzle] | None:
        return cls.match(unknown_puzzle=UnknownPuzzle(known_puzzle=uncurried.mod.curry(*uncurried.args.as_iter())))

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> CATPuzzle[UnknownPuzzle] | None:
        cat_puzzles = CATCorePuzzles()
        if unknown_puzzle.mod != cat_puzzles.cat_mod or unknown_puzzle.curried_args is None:
            return None
        _, tail_hash_prog, inner_puzzle_prog = unknown_puzzle.curried_args
        return CATPuzzle(
            tail_hash=bytes32(tail_hash_prog.as_atom()),
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle_prog),
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class CAT(CATPuzzle[_T_InnerPuzzle], Generic[_T_InnerPuzzle]):
    if TYPE_CHECKING:
        _smart_coin_protocol_check: ClassVar[SmartCoin] = cast("CAT[_T_InnerPuzzle]", None)

    coin: Coin
    lineage_proof: LineageProof


# information needed to spend a cc
@dataclasses.dataclass(kw_only=True, frozen=True)
class SpendableCAT(Generic[_T_InnerPuzzle]):
    cat: CAT[_T_InnerPuzzle]
    inner_solution: Solution
    extra_delta: int = 0
    limitations_solution: Program = dataclasses.field(default_factory=lambda: Program.NIL)
    limitations_program_reveal: Program = dataclasses.field(default_factory=lambda: Program.NIL)

    @property
    def inner_conditions(self) -> list[Condition]:
        return list(
            parse_conditions_non_consensus(
                run(self.cat.inner_puzzle.puzzle, self.inner_solution.as_program()).as_iter()
            )
        )


_T_Solution = TypeVar("_T_Solution", bound=Solution)


@dataclasses.dataclass(kw_only=True, frozen=True)
class TAILCondition(Condition, Generic[_T_InnerPuzzle, _T_Solution]):
    puzzle: _T_InnerPuzzle
    solution: _T_Solution

    def __post_init__(self) -> None:
        # Driver-only condition; fields are not streamable-serializable.
        return

    def to_program(self) -> Program:
        return Program.to([ConditionOpcode.CREATE_COIN, None, -113, self.puzzle.puzzle, self.solution.as_program()])

    @classmethod
    def from_program(cls, program: Program) -> TAILCondition[UnknownPuzzle, UnknownSolution]:  # type: ignore[override]
        return TAILCondition(
            puzzle=UnknownPuzzle(known_puzzle=program.at("rrrf")),
            solution=UnknownSolution(solution=program.at("rrrrf")),
        )


def _subtotals_for_deltas(deltas: list[int]) -> list[int]:
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


def _next_info_for_spendable_cat(spendable_cat: SpendableCAT[_T_InnerPuzzle]) -> Program:
    c = spendable_cat.cat.coin
    list = [c.parent_coin_info, spendable_cat.cat.inner_puzzle.puzzle_hash, c.amount]
    return Program.to(list)


# This should probably return UnsignedSpendBundle if that type ever exists
def unsigned_spend_bundle_for_spendable_cats(
    spendable_cat_list: list[SpendableCAT[_T_InnerPuzzle]],
) -> WalletSpendBundle:
    """
    Given a list of `SpendableCAT` objects, create a `WalletSpendBundle` that spends all those coins.
    Note that no signing is done here, so it falls on the caller to sign the resultant bundle.
    """

    N = len(spendable_cat_list)

    # figure out what the deltas are by running the inner puzzles & solutions
    deltas: list[int] = []
    for spend_info in spendable_cat_list:
        total = spend_info.extra_delta * -1
        for condition in spend_info.inner_conditions:
            if isinstance(condition, CreateCoin):  # -113 in bytes
                total += condition.amount
        deltas.append(spend_info.cat.coin.amount - total)

    if sum(deltas) != 0:
        raise ValueError("input and output amounts don't match")

    subtotals = _subtotals_for_deltas(deltas)

    infos_for_next = []
    infos_for_me = []
    ids = []
    for spendable_cat in spendable_cat_list:
        infos_for_next.append(_next_info_for_spendable_cat(spendable_cat))
        infos_for_me.append(Program.to(coin_as_list(spendable_cat.cat.coin)))
        ids.append(spendable_cat.cat.coin.name())

    coin_spends = []
    for index in range(N):
        spend_info = spendable_cat_list[index]

        prev_index = (index - 1) % N
        next_index = (index + 1) % N
        prev_id = ids[prev_index]
        my_info = infos_for_me[index]
        next_info = infos_for_next[next_index]

        solution = [
            spend_info.inner_solution.as_program(),
            spend_info.cat.lineage_proof.to_program(),
            prev_id,
            my_info,
            next_info,
            subtotals[index],
            spend_info.extra_delta,
        ]
        coin_spend = make_spend(spend_info.cat.coin, spend_info.cat.puzzle, Program.to(solution))
        coin_spends.append(coin_spend)

    return WalletSpendBundle(coin_spends, G2Element())
