from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.clawback.cb_puzzles import ClawbackInfo, construct_p2_merkle_puzzle


class ClawbackPuzzleDecorator:
    clawback_info: ClawbackInfo

    @staticmethod
    def create(config: Dict[str, Any]) -> ClawbackPuzzleDecorator:
        self = ClawbackPuzzleDecorator()
        self.clawback_info = ClawbackInfo(config.get("clawback_timelock", 0), Program.to([]))
        return self

    def decorate(self, inner_puzzle: Program) -> Program:
        clawback_info = dataclasses.replace(self.clawback_info, inner_puzzle=inner_puzzle)
        inner_puzzle = clawback_info.outer_puzzle()
        return inner_puzzle

    def decorate_target_puzhash(self, inner_puzzle: Program, target_puzhash: bytes32) -> Tuple[Program, bytes32]:
        clawback_info = dataclasses.replace(self.clawback_info, inner_puzzle=inner_puzzle)
        return clawback_info.outer_puzzle(), construct_p2_merkle_puzzle(clawback_info, target_puzhash).get_tree_hash()

    def solve(
        self, inner_puzzle: Program, primaries: List[Dict[str, Any]], inner_solution: Program
    ) -> Tuple[Program, Program]:
        clawback_info = dataclasses.replace(self.clawback_info, inner_puzzle=inner_puzzle)
        solution_data = [primary["puzzle_hash"] for primary in primaries]
        solution_data.append(clawback_info.puzzle_hash())
        validator_solution = Program.to([[solution_data, inner_solution]])
        return clawback_info.outer_puzzle(), validator_solution

    def decorate_memos(
        self, inner_puzzle: Program, target_puzhash: bytes32, memos: List[bytes]
    ) -> Tuple[Program, List[bytes]]:
        clawback_info = dataclasses.replace(self.clawback_info, inner_puzzle=inner_puzzle)
        memos.insert(0, target_puzhash)
        return clawback_info.outer_puzzle(), memos
