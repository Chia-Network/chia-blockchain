from __future__ import annotations

from chia_rs.sized_bytes import bytes32
from typing_extensions import Protocol

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.uncurried_puzzle import UncurriedPuzzle


class DriverProtocol(Protocol):
    def match(self, puzzle: UncurriedPuzzle) -> PuzzleInfo | None: ...

    def get_inner_puzzle(
        self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle, solution: Program | None = ...
    ) -> Program | None: ...

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Program | None: ...

    def asset_id(self, constructor: PuzzleInfo) -> bytes32 | None: ...

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program: ...

    def solve(
        self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program
    ) -> Program: ...
