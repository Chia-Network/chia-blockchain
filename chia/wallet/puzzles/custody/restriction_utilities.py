from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

from chia_puzzles_py import programs as puzzle_mods
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.custody.custody_architecture import MemberOrDPuz, MIPSComponent, MIPSComponentBase, Restriction
from chia.wallet.puzzles.puzzle_drivers import (
    DelegatedPuzzleAndSolution,
    InnerPuzzle,
    PuzzleWithPuzzleHash,
    UnknownPuzzle,
    UnknownSolution,
)

UNUSED_NONCE = 0

ENFORCE_DPUZ_WRAPPERS = Program.from_bytes(puzzle_mods.ENFORCE_DPUZ_WRAPPERS)
ENFORCE_DPUZ_WRAPPERS_HASH = bytes32(puzzle_mods.ENFORCE_DPUZ_WRAPPERS_HASH)
ADD_DPUZ_WRAPPER = Program.from_bytes(puzzle_mods.ADD_DPUZ_WRAPPER)
QUOTED_ADD_DPUZ_WRAPPER_HASH = Program.to((1, ADD_DPUZ_WRAPPER)).get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class ValidatorStackRestriction(MIPSComponentBase, PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _restriction_protocol_check: ClassVar[Restriction[MemberOrDPuz]] = cast("ValidatorStackRestriction", None)
    required_wrappers: Sequence[MIPSComponent]

    @property
    def wrappers(self) -> Sequence[MIPSComponent]:
        return [wrapper.with_nonce(self.nonce) for wrapper in self.required_wrappers]

    @property
    def member_not_dpuz(self) -> bool:
        return False

    @property
    def memo(self) -> Program:
        return Program.to([wrapper.memo for wrapper in self.wrappers])

    @property
    def required_quoted_wrappers_hashes(self) -> list[bytes32]:
        required_quoted_wrappers_hashes = []
        for wrapper in self.wrappers:
            puzhash = wrapper.puzzle_hash
            required_quoted_wrappers_hashes.append(Program.to((1, puzhash)).get_tree_hash_precalc(puzhash))

        return required_quoted_wrappers_hashes

    @property
    def puzzle(self) -> Program:
        return ENFORCE_DPUZ_WRAPPERS.curry(QUOTED_ADD_DPUZ_WRAPPER_HASH, self.required_quoted_wrappers_hashes)

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return (
            Program.to(ENFORCE_DPUZ_WRAPPERS_HASH)
            .curry(QUOTED_ADD_DPUZ_WRAPPER_HASH, self.required_quoted_wrappers_hashes)
            .get_tree_hash_precalc(ENFORCE_DPUZ_WRAPPERS_HASH)
        )

    def solve(self, original_dpuz: Program) -> Program:
        return Program.to([original_dpuz.get_tree_hash()])

    def modify_delegated_puzzle_and_solution(
        self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution, wrapper_solutions: list[Program]
    ) -> DelegatedPuzzleAndSolution:
        if len(wrapper_solutions) != len(self.wrappers):
            raise ValueError("Number of wrapper solutions does not match number of required wrappers")

        for wrapper, wrapper_solution in zip(reversed(self.wrappers), reversed(wrapper_solutions)):
            delegated_puzzle_and_solution = DelegatedPuzzleAndSolution(
                puzzle=UnknownPuzzle(
                    known_puzzle=ADD_DPUZ_WRAPPER.curry(wrapper.puzzle, delegated_puzzle_and_solution.puzzle.puzzle)
                ),
                solution=UnknownSolution(
                    solution=Program.to([wrapper_solution, delegated_puzzle_and_solution.solution.as_program()])
                ),
            )

        return delegated_puzzle_and_solution

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> InnerPuzzle | None: ...
