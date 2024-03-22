from __future__ import annotations

from typing import Optional

from typing_extensions import Protocol

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.uncurried_puzzle import UncurriedPuzzle


class DriverProtocol(Protocol):
    def match(self, puzzle: UncurriedPuzzle) -> Optional[PuzzleInfo]: ...

    def get_inner_puzzle(self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle) -> Optional[Program]: ...

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Optional[Program]: ...

    def asset_id(self, constructor: PuzzleInfo) -> Optional[bytes32]: ...

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program: ...

    def solve(
        self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program
    ) -> Program: ...
