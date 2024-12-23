"""
Pay to delegated conditions

In this puzzle program, the solution must be a signed list of conditions, which
is returned literally.
"""

from __future__ import annotations

from chia_puzzles_py.programs import P2_DELEGATED_CONDITIONS

from chia.types.blockchain_format.program import Program

MOD = Program.from_bytes(P2_DELEGATED_CONDITIONS)


def puzzle_for_pk(public_key: Program) -> Program:
    return MOD.curry(public_key)


def solution_for_conditions(conditions: Program) -> Program:
    return conditions.to([conditions])
