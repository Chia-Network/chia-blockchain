from __future__ import annotations

from dataclasses import dataclass

from chia.types.blockchain_format.program import Program


@dataclass(frozen=True)
class UncurriedPuzzle:
    mod: Program
    args: Program


def uncurry_puzzle(puzzle: Program) -> UncurriedPuzzle:
    return UncurriedPuzzle(*puzzle.uncurry())
