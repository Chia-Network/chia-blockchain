from __future__ import annotations

from dataclasses import dataclass

from chia.wallet.puzzles import puzzle_drivers


@dataclass(frozen=True, kw_only=True)
class PuzzleDriverSet:
    name: str
    puzzle: type[puzzle_drivers.Puzzle]
    solution: type[puzzle_drivers.Solution]


DRIVER_REGISTRY = [
    PuzzleDriverSet(name="unknown", puzzle=puzzle_drivers.UnknownPuzzle, solution=puzzle_drivers.UnknownSolution),
    PuzzleDriverSet(name="acs", puzzle=puzzle_drivers.ACSPuzzle, solution=puzzle_drivers.ACSSolution),
    PuzzleDriverSet(name="nil", puzzle=puzzle_drivers.NilPuzzle, solution=puzzle_drivers.NilSolution),
    PuzzleDriverSet(name="p2_conditions", puzzle=puzzle_drivers.P2Conditions, solution=puzzle_drivers.NilSolution),
]
