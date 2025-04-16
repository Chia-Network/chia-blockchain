from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram


@dataclass(frozen=True)
class UncurriedPuzzle:
    mod: Program
    args: Program


def uncurry_puzzle(puzzle: Union[Program, SerializedProgram]) -> UncurriedPuzzle:
    return UncurriedPuzzle(*puzzle.uncurry())
