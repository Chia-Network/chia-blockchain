from __future__ import annotations

from typing import Any, Dict, List, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64
from chia.util.streamable import VersionedBlob
from chia.wallet.payment import Payment
from chia.wallet.puzzles.clawback.drivers import create_merkle_puzzle
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata, ClawbackVersion
from chia.wallet.util.wallet_types import RemarkDataType


class ClawbackPuzzleDecorator:
    """
    This class is a wrapper for clawback puzzles. It allows us to add Clawback characteristics to the inner puzzle.
    """

    time_lock: uint64

    @staticmethod
    def create(config: Dict[str, Any]) -> ClawbackPuzzleDecorator:
        self = ClawbackPuzzleDecorator()
        self.time_lock = uint64(config.get("clawback_timelock", 0))
        return self

    def decorate(self, inner_puzzle: Program) -> Program:
        # We don't wrap anything for the Clawback
        return inner_puzzle

    def decorate_target_puzzle_hash(
        self,
        inner_puzzle: Program,
        target_puzzle_hash: bytes32,
    ) -> Tuple[Program, bytes32]:
        return (
            self.decorate(inner_puzzle),
            create_merkle_puzzle(self.time_lock, inner_puzzle.get_tree_hash(), target_puzzle_hash).get_tree_hash(),
        )

    def solve(
        self, inner_puzzle: Program, primaries: List[Payment], inner_solution: Program
    ) -> Tuple[Program, Program]:
        # Append REMARK condition [1, "CLAWBACK", TIME_LOCK, SENDER_PUZHSAH, RECIPIENT_PUZHSAH]
        if len(primaries) == 1:
            recipient_puzhash = primaries[0].puzzle_hash
            metadata = ClawbackMetadata(self.time_lock, inner_puzzle.get_tree_hash(), recipient_puzhash)
            remark_condition = Program.to(
                [
                    ConditionOpcode.REMARK.value,
                    RemarkDataType.CLAWBACK,
                    bytes(VersionedBlob(ClawbackVersion.V1.value, bytes(metadata))),
                ]
            )
            # Insert the REMARK condition into the condition list
            conditions = remark_condition.cons(inner_solution.rest().first().rest())
            conditions = inner_solution.rest().first().first().cons(conditions)
            inner_solution = inner_solution.replace(rf=conditions)
        return self.decorate(inner_puzzle), inner_solution

    def decorate_memos(
        self, inner_puzzle: Program, target_puzzle_hash: bytes32, memos: List[bytes]
    ) -> Tuple[Program, List[bytes]]:
        memos.insert(0, target_puzzle_hash)
        return self.decorate(inner_puzzle), memos
