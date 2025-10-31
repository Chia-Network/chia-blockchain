from __future__ import annotations

from dataclasses import dataclass

from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.custody.custody_architecture import DelegatedPuzzleAndSolution, Puzzle
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

UNUSED_NONCE = 0

ENFORCE_DPUZ_WRAPPERS = load_clvm_maybe_recompile(
    "enforce_dpuz_wrappers.clsp", package_or_requirement="chia.wallet.puzzles.custody.restriction_puzzles"
)
ENFORCE_DPUZ_WRAPPERS_HASH = ENFORCE_DPUZ_WRAPPERS.get_tree_hash()
ADD_DPUZ_WRAPPER = load_clvm_maybe_recompile(
    "add_dpuz_wrapper.clsp", package_or_requirement="chia.wallet.puzzles.custody.restriction_puzzles"
)
QUOTED_ADD_DPUZ_WRAPPER_HASH = Program.to((1, ADD_DPUZ_WRAPPER)).get_tree_hash()


@dataclass(frozen=True)
class ValidatorStackRestriction:
    required_wrappers: list[Puzzle]

    @property
    def member_not_dpuz(self) -> bool:
        return False

    def memo(self, nonce: int) -> Program:
        return Program.to([wrapper.memo(nonce) for wrapper in self.required_wrappers])

    def required_quoted_wrappers_hashes(self, nonce: int) -> list[bytes32]:
        required_quoted_wrappers_hashes = []
        for wrapper in self.required_wrappers:
            puzhash = wrapper.puzzle_hash(nonce)
            required_quoted_wrappers_hashes.append(Program.to((1, puzhash)).get_tree_hash_precalc(puzhash))

        return required_quoted_wrappers_hashes

    def puzzle(self, nonce: int) -> Program:
        return ENFORCE_DPUZ_WRAPPERS.curry(QUOTED_ADD_DPUZ_WRAPPER_HASH, self.required_quoted_wrappers_hashes(nonce))

    def puzzle_hash(self, nonce: int) -> bytes32:
        return (
            Program.to(ENFORCE_DPUZ_WRAPPERS_HASH)
            .curry(QUOTED_ADD_DPUZ_WRAPPER_HASH, self.required_quoted_wrappers_hashes(nonce))
            .get_tree_hash_precalc(ENFORCE_DPUZ_WRAPPERS_HASH)
        )

    def modify_delegated_puzzle_and_solution(
        self, delegated_puzzle_and_solution: DelegatedPuzzleAndSolution, wrapper_solutions: list[Program]
    ) -> DelegatedPuzzleAndSolution:
        for wrapper, wrapper_solution in zip(self.required_wrappers, wrapper_solutions):
            delegated_puzzle_and_solution = DelegatedPuzzleAndSolution(
                ADD_DPUZ_WRAPPER.curry(wrapper.puzzle(UNUSED_NONCE), delegated_puzzle_and_solution.puzzle),
                Program.to([wrapper_solution, delegated_puzzle_and_solution.solution]),
            )

        return delegated_puzzle_and_solution
