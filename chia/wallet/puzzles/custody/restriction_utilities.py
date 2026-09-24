from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from chia_puzzles_py import programs as puzzle_mods
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.custody.custody_architecture import MIPSComponent, MIPSComponentBase
from chia.wallet.puzzles.puzzle_drivers import (
    DelegatedPuzzleAndSolution,
    Puzzle,
    Solution,
    UnknownPuzzle,
    UnknownSolution,
)

UNUSED_NONCE = 0

ENFORCE_DPUZ_WRAPPERS = Program.from_bytes(puzzle_mods.ENFORCE_DPUZ_WRAPPERS)
ENFORCE_DPUZ_WRAPPERS_HASH = bytes32(puzzle_mods.ENFORCE_DPUZ_WRAPPERS_HASH)
ADD_DPUZ_WRAPPER = Program.from_bytes(puzzle_mods.ADD_DPUZ_WRAPPER)
QUOTED_ADD_DPUZ_WRAPPER_HASH = Program.to((1, ADD_DPUZ_WRAPPER)).get_tree_hash()


@dataclass(kw_only=True, frozen=True)
class ValidatorStackRestriction(MIPSComponentBase):
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
            puzhash = wrapper.tree_hash
            required_quoted_wrappers_hashes.append(Program.to((1, puzhash)).get_tree_hash_precalc(puzhash))

        return required_quoted_wrappers_hashes

    @property
    def program(self) -> Program:
        return ENFORCE_DPUZ_WRAPPERS.curry(QUOTED_ADD_DPUZ_WRAPPER_HASH, self.required_quoted_wrappers_hashes)

    @property
    def tree_hash_optimized(self) -> bytes32:
        return (
            Program.to(ENFORCE_DPUZ_WRAPPERS_HASH)
            .curry(QUOTED_ADD_DPUZ_WRAPPER_HASH, self.required_quoted_wrappers_hashes)
            .get_tree_hash_precalc(ENFORCE_DPUZ_WRAPPERS_HASH)
        )

    def modify_delegated_puzzle_and_solution(
        self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution, wrapper_solutions: Sequence[Solution]
    ) -> DelegatedPuzzleAndSolution:
        if len(wrapper_solutions) != len(self.wrappers):
            raise ValueError("Number of wrapper solutions does not match number of required wrappers")

        for wrapper, wrapper_solution in zip(reversed(self.wrappers), reversed(wrapper_solutions)):
            delegated_puzzle_and_solution = DelegatedPuzzleAndSolution(
                puzzle=UnknownPuzzle(
                    known_program=ADD_DPUZ_WRAPPER.curry(wrapper.program, delegated_puzzle_and_solution.puzzle.program)
                ),
                solution=UnknownSolution(
                    program=Program.to([wrapper_solution.program, delegated_puzzle_and_solution.solution.program])
                ),
            )

        return delegated_puzzle_and_solution

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> ValidatorStackRestriction | None: ...


@dataclass(kw_only=True, frozen=True)
class ValidatorStackRestrictionSolution:
    original_dpuz_hash: bytes32

    @classmethod
    def from_dpuz(cls, original_dpuz: Puzzle | Program) -> ValidatorStackRestrictionSolution:
        if isinstance(original_dpuz, Program):
            return cls(original_dpuz_hash=original_dpuz.get_tree_hash())
        return cls(original_dpuz_hash=original_dpuz.tree_hash)

    @property
    def program(self) -> Program:
        return Program.to([self.original_dpuz_hash])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> ValidatorStackRestrictionSolution | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
        if len(list_of_values) != 1:
            return None
        try:
            return cls(original_dpuz_hash=bytes32(list_of_values[0].as_atom()))
        except ValueError:
            return None
