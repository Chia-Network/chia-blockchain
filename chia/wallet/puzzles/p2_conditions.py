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

from chia.types.blockchain_format.program import Program

from .load_clvm import load_clvm_maybe_recompile

MOD = load_clvm_maybe_recompile("p2_conditions.clvm")


def puzzle_for_conditions(conditions) -> Program:
    return MOD.run([conditions])


def solution_for_conditions(conditions) -> Program:
    return Program.to([puzzle_for_conditions(conditions), 0])
