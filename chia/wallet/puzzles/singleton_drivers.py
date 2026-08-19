from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, cast

from chia_rs import Coin, CoinSpend
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.program import Program, run
from chia.types.coin_spend import make_spend
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    Condition,
    CreateCoin,
    MessageParticipant,
    SendMessage,
    UnknownCondition,
    parse_conditions_non_consensus,
)
from chia.wallet.lineage_proof import LineageProof, LineageProofField
from chia.wallet.puzzles.custody.custody_architecture import PuzzleWithRestrictions
from chia.wallet.puzzles.custody.member_puzzles import SINGLETON_MEMBER_MOD, SingletonMember
from chia.wallet.puzzles.puzzle_drivers import (
    DelegatedPuzzleAndSolution,
    InnerPuzzle,
    OptimizedPuzzleHashPuzzle,
    OuterPuzzle,
    PuzzleWithPuzzleHash,
    SmartCoin,
    Solution,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
)
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash, curry_and_treehash


@dataclass(kw_only=True, frozen=True)
class SingletonCorePuzzles:
    singleton_mod: Program = field(default_factory=lambda: SINGLETON_MOD)
    singleton_mod_hash_pre_computed: bytes32 | None = SINGLETON_MOD_HASH
    singleton_launcher: Program = field(default_factory=lambda: SINGLETON_LAUNCHER)
    singleton_launcher_hash_pre_computed: bytes32 | None = SINGLETON_LAUNCHER_HASH
    hash_of_quoted_mod_hash_pre_computed: bytes32 | None = calculate_hash_of_quoted_mod_hash(SINGLETON_MOD_HASH)

    @cached_property
    def singleton_mod_hash(self) -> bytes32:
        if self.singleton_mod_hash_pre_computed is not None:
            return self.singleton_mod_hash_pre_computed
        else:
            return self.singleton_mod.get_tree_hash()

    @cached_property
    def hash_of_quoted_mod_hash(self) -> bytes32:
        if self.hash_of_quoted_mod_hash_pre_computed is not None:
            return self.hash_of_quoted_mod_hash_pre_computed
        else:
            return calculate_hash_of_quoted_mod_hash(self.singleton_mod_hash)

    @cached_property
    def singleton_launcher_hash(self) -> bytes32:
        if self.singleton_launcher_hash_pre_computed is not None:
            return self.singleton_launcher_hash_pre_computed
        else:
            return self.singleton_launcher.get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class SingletonStruct:
    launcher_id: bytes32
    singleton_puzzles: SingletonCorePuzzles = SingletonCorePuzzles()

    @cached_property
    def program(self) -> Program:
        return Program.to(
            (
                self.singleton_puzzles.singleton_mod_hash,
                (self.launcher_id, self.singleton_puzzles.singleton_launcher_hash),
            )
        )

    @cached_property
    def struct_hash(self) -> bytes32:
        return self.program.get_tree_hash()


_T_InnerPuzzle = TypeVar("_T_InnerPuzzle", bound=InnerPuzzle)


@dataclass(kw_only=True, frozen=True)
class SingletonPuzzle(PuzzleWithPuzzleHash, Generic[_T_InnerPuzzle]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast("SingletonPuzzle[_T_InnerPuzzle]", None)
        _optimized_ph_protocol_check: ClassVar[OptimizedPuzzleHashPuzzle] = cast(
            "SingletonPuzzle[_T_InnerPuzzle]", None
        )

    launcher_id: bytes32
    inner_puzzle: _T_InnerPuzzle
    singleton_puzzles: ClassVar[SingletonCorePuzzles] = SingletonCorePuzzles()
    melt_condition: ClassVar[UnknownCondition] = UnknownCondition(
        opcode=Program.to(51), args=[Program.NIL, Program.to(-113)]
    )

    @property
    def singleton_struct(self) -> SingletonStruct:
        return SingletonStruct(launcher_id=self.launcher_id, singleton_puzzles=self.singleton_puzzles)

    @property
    def puzzle(self) -> Program:
        return self.singleton_struct.singleton_puzzles.singleton_mod.curry(
            self.singleton_struct.program, self.inner_puzzle.puzzle
        )

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return curry_and_treehash(
            self.singleton_puzzles.hash_of_quoted_mod_hash,
            self.singleton_struct.struct_hash,
            self.inner_puzzle.puzzle_hash,
        )

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> SingletonPuzzle[UnknownPuzzle] | None:
        if unknown_puzzle.mod == cls.singleton_puzzles.singleton_mod or unknown_puzzle.curried_args is None:
            return None
        singleton_struct, inner_puzzle = unknown_puzzle.curried_args
        return SingletonPuzzle(
            launcher_id=bytes32(singleton_struct.at("rf").as_atom()),
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle),
        )

    def with_inner_puzzle(self, inner_puzzle: InnerPuzzle) -> Any:
        # should be used as little as possible because it doesn't seem possible to return a
        # newly paramed instance of the current type so we have to resort to Any
        return replace(self, inner_puzzle=inner_puzzle)  # type: ignore[arg-type]


@dataclass(kw_only=True)
class SingletonSolution:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Solution] = cast("SingletonSolution", None)

    lineage_proof: LineageProof
    coin_amount: uint64
    inner_solution: Solution

    def as_program(self) -> Program:
        return Program.to([self.lineage_proof.to_program(), self.coin_amount, self.inner_solution.as_program()])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> SingletonSolution | None:
        if unknown_solution.as_program().atom is not None:
            return None
        list_of_values = list(unknown_solution.as_program().as_iter())
        if len(list_of_values) != 3:
            return None
        num_lineage_proof_fields = len(list(list_of_values[0].as_iter()))
        return cls(
            lineage_proof=LineageProof.from_program(
                list_of_values[0],
                [LineageProofField.PARENT_NAME, LineageProofField.AMOUNT]
                if num_lineage_proof_fields == 2
                else [LineageProofField.PARENT_NAME, LineageProofField.INNER_PUZZLE_HASH, LineageProofField.AMOUNT],
            ),
            coin_amount=uint64(list_of_values[1].as_int()),
            inner_solution=UnknownSolution(list_of_values[2]),
        )


@dataclass(kw_only=True, frozen=True)
class SingletonLaunchInfo(Generic[_T_InnerPuzzle]):
    desired_inner_puzzle: _T_InnerPuzzle
    key_value_hints: dict[str, str]
    amount: uint64 = uint64(1)

    def __post_init__(self) -> None:
        if self.amount % 2 == 0:
            raise ValueError("Coin amount cannot be even. Subtract one mojo.")


@dataclass(kw_only=True, frozen=True)
class SingletonLaunchResult(Generic[_T_InnerPuzzle]):
    necessary_conditions: list[Condition]
    necessary_spends: list[CoinSpend]
    launched_singleton: Singleton[_T_InnerPuzzle]


def _new_create_coin_from_inner_puzzle_and_solution(inner_puzzle: InnerPuzzle, solution: Solution) -> CreateCoin:
    return next(
        cond
        for cond in parse_conditions_non_consensus(run(inner_puzzle.puzzle, solution.as_program()).as_iter())
        if isinstance(cond, CreateCoin) and cond.amount % 2 == 1
    )


@dataclass(kw_only=True, frozen=True)
class Singleton(SingletonPuzzle[_T_InnerPuzzle]):
    if TYPE_CHECKING:
        _smart_coin_protocol_check: ClassVar[SmartCoin] = cast("Singleton[_T_InnerPuzzle]", None)

    coin: Coin
    lineage_proof: LineageProof

    _T_LaunchInnerPuzzle = TypeVar("_T_LaunchInnerPuzzle", bound=InnerPuzzle)

    @classmethod
    def launch(
        cls,
        *,
        origin_coin: Coin,
        launch_info: SingletonLaunchInfo[_T_LaunchInnerPuzzle],
    ) -> SingletonLaunchResult[_T_LaunchInnerPuzzle]:
        if (launch_info.amount % 2) == 0:
            raise ValueError("Coin amount cannot be even. Subtract one mojo.")

        launcher_coin = Coin(origin_coin.name(), cls.singleton_puzzles.singleton_launcher_hash, launch_info.amount)
        launcher_id = launcher_coin.name()
        new_singleton_puzzle = SingletonPuzzle(launcher_id=launcher_id, inner_puzzle=launch_info.desired_inner_puzzle)

        launcher_solution = Program.to(
            [
                new_singleton_puzzle.puzzle_hash,
                launch_info.amount,
                [(k, v) for k, v in launch_info.key_value_hints.items()],
            ]
        )
        create_launcher_condition = CreateCoin(
            puzzle_hash=cls.singleton_puzzles.singleton_launcher_hash, amount=launch_info.amount
        )
        assert_launcher_announcement = AssertCoinAnnouncement(
            asserted_id=launcher_id, asserted_msg=launcher_solution.get_tree_hash()
        )

        return SingletonLaunchResult(
            necessary_conditions=[create_launcher_condition, assert_launcher_announcement],
            necessary_spends=[
                make_spend(
                    launcher_coin,
                    cls.singleton_puzzles.singleton_launcher,
                    launcher_solution,
                )
            ],
            launched_singleton=Singleton(
                coin=Coin(
                    parent_coin_info=launcher_id,
                    puzzle_hash=new_singleton_puzzle.puzzle_hash,
                    amount=launch_info.amount,
                ),
                lineage_proof=LineageProof(parent_name=launcher_coin.parent_coin_info, amount=launcher_coin.amount),
                launcher_id=launcher_id,
                inner_puzzle=launch_info.desired_inner_puzzle,
            ),
        )

    def spend(self, inner_solution: Solution) -> CoinSpend:
        return make_spend(
            coin=self.coin,
            puzzle_reveal=self.puzzle,
            solution=SingletonSolution(
                lineage_proof=self.lineage_proof,
                coin_amount=self.coin.amount,
                inner_solution=inner_solution,
            ).as_program(),
        )

    def action_spend(self, inner_solution: Solution) -> tuple[CoinSpend, Singleton[UnknownPuzzle]]:
        next_create_coin = _new_create_coin_from_inner_puzzle_and_solution(self.inner_puzzle, inner_solution)
        next_singleton_puzzle = SingletonPuzzle(
            launcher_id=self.launcher_id, inner_puzzle=UnknownPuzzle(known_puzzle_hash=next_create_coin.puzzle_hash)
        )
        return self.spend(inner_solution), Singleton(
            coin=Coin(self.coin.name(), puzzle_hash=next_singleton_puzzle.puzzle_hash, amount=next_create_coin.amount),
            lineage_proof=LineageProof(
                parent_name=self.coin.parent_coin_info,
                inner_puzzle_hash=self.inner_puzzle.puzzle_hash,
                amount=self.coin.amount,
            ),
            launcher_id=self.launcher_id,
            inner_puzzle=next_singleton_puzzle.inner_puzzle,
        )

    def claim_p2_singletons(
        self,
        *,
        rewards_to_claim: Sequence[P2Singleton],
        reward_delegated_puzzles_and_solutions: list[DelegatedPuzzleAndSolution],
    ) -> tuple[list[CoinSpend], list[SendMessage]]:
        if len(rewards_to_claim) != len(reward_delegated_puzzles_and_solutions):
            raise ValueError("Number of rewards and delegated puzzles and solutions must match")
        messages_to_send = [
            SendMessage(
                msg=dpuz_and_sol.puzzle.puzzle_hash,
                sender=MessageParticipant(puzzle_hash_committed=self.puzzle_hash),
                receiver=MessageParticipant(coin_id_committed=reward.coin.name()),
            )
            for reward, dpuz_and_sol in zip(rewards_to_claim, reward_delegated_puzzles_and_solutions)
        ]
        return [
            make_spend(
                coin=reward.coin,
                puzzle_reveal=reward.puzzle,
                solution=reward.solve(
                    self.inner_puzzle.puzzle_hash,
                    delegated_puzzle_and_solution=dpuz_and_sol,
                ),
            )
            for reward, dpuz_and_sol in zip(rewards_to_claim, reward_delegated_puzzles_and_solutions)
        ], messages_to_send


@dataclass(kw_only=True, frozen=True)
class P2SingletonPuzzle(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[InnerPuzzle] = cast("P2SingletonPuzzle", None)

    singleton_id: bytes32
    nonce: int = 0

    @property
    def singleton_member(self) -> SingletonMember:
        return SingletonMember(singleton_id=self.singleton_id)

    @property
    def _puzzle_with_restrictions(self) -> PuzzleWithRestrictions:
        return PuzzleWithRestrictions(nonce=self.nonce, restrictions=[], member=self.singleton_member)

    @property
    def puzzle(self) -> Program:
        return self._puzzle_with_restrictions.puzzle

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return self._puzzle_with_restrictions.puzzle_hash

    def solve(
        self, singleton_inner_puzzle_hash: bytes32, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution
    ) -> Program:
        return self._puzzle_with_restrictions.solve(
            [],
            [],
            self.singleton_member.solve(singleton_inner_puzzle_hash),
            delegated_puzzle_and_solution,
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> InnerPuzzle | None:
        mips_match = PuzzleWithRestrictions.match(unknown_puzzle=unknown_puzzle, solution=solution)
        if mips_match is None:
            return None
        assert isinstance(mips_match, PuzzleWithRestrictions)
        assert isinstance(mips_match.puzzle, UnknownPuzzle)
        if mips_match.puzzle.mod != SINGLETON_MEMBER_MOD or mips_match.puzzle.curried_args is None:
            return None
        (singleton_struct_prog,) = mips_match.puzzle.curried_args
        return cls(singleton_id=bytes32(singleton_struct_prog.at("rf").as_atom()))


@dataclass(kw_only=True, frozen=True)
class P2Singleton(P2SingletonPuzzle):
    coin: Coin
