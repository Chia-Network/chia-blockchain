"""
Pay to conditions

In this puzzle program, the solution is ignored. The reveal of the puzzle
returns a fixed list of conditions. This roughly corresponds to OP_SECURETHEBAG
in bitcoin.

This is a pretty useless most of the time. But some (most?) solutions
require a delegated puzzle program, so in those cases, this is just what
the doctor ordered.
"""

from __future__ import annotations

from chia_puzzles_py.programs import P2_CONDITIONS

from chia.types.blockchain_format.program import Program

MOD = Program.from_bytes(P2_CONDITIONS)


def puzzle_for_conditions(conditions) -> Program:
    return MOD.run([conditions])


def solution_for_conditions(conditions) -> Program:
    return Program.to([puzzle_for_conditions(conditions), 0])
