from __future__ import annotations

from typing import Any, Dict, List, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64
from chia.util.misc import VersionedBlob
from chia.wallet.puzzles.clawback.drivers import create_merkle_puzzle
from chia.wallet.puzzles.clawback.metadata import CLAWBACK_VERSION, ClawbackMetadata
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import MOD
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.puzzle_decorator_type import PuzzleDecoratorType


class ClawbackPuzzleDecorator:
    time_lock: uint64

    @staticmethod
    def create(config: Dict[str, Any]) -> ClawbackPuzzleDecorator:
        self = ClawbackPuzzleDecorator()
        self.time_lock = uint64(config.get("clawback_timelock", 0))
        return self

    def decorate(self, inner_puzzle: Program) -> Program:
        # We don't wrap anything for the Clawback
        return inner_puzzle

    def decorate_target_puzhash(
        self,
        inner_puzzle: Program,
        target_puzhash: bytes32,
    ) -> Tuple[Program, bytes32]:
        return (
            self.decorate(inner_puzzle),
            create_merkle_puzzle(self.time_lock, inner_puzzle.get_tree_hash(), target_puzhash).get_tree_hash(),
        )

    def solve(
        self, inner_puzzle: Program, primaries: List[Dict[str, Any]], inner_solution: Program
    ) -> Tuple[Program, Program]:
        # Append REMARK condition [1, "CLAWBACK", TIME_LOCK, SENDER_PUZHSAH, RECIPIENT_PUZHSAH]
        if len(primaries) == 1 and "puzzlehash" in primaries[0]:
            # Check if the inner puzzle is a standard P2 puzzle
            uncurried = uncurry_puzzle(inner_puzzle)
            if MOD != uncurried.mod:
                raise ValueError("Clawback only supports primitive inner P2 puzzle.")
            recipient_puzhash = primaries[0]["puzzlehash"]
            metadata = ClawbackMetadata(self.time_lock, False, inner_puzzle.get_tree_hash(), recipient_puzhash)
            remark_condition = Program.to(
                [
                    ConditionOpcode.REMARK.value,
                    PuzzleDecoratorType.CLAWBACK.name,
                    bytes(VersionedBlob(CLAWBACK_VERSION.V1.value, bytes(metadata))),
                ]
            ).as_python()

            conditions = inner_solution.rest().first().as_python()
            conditions.insert(1, remark_condition)
            inner_solution = inner_solution.replace(rf=conditions)
        return self.decorate(inner_puzzle), inner_solution

    def decorate_memos(
        self, inner_puzzle: Program, target_puzhash: bytes32, memos: List[bytes]
    ) -> Tuple[Program, List[bytes]]:
        memos.insert(0, target_puzhash)
        return self.decorate(inner_puzzle), memos
