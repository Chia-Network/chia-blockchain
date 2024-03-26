"""
Pay to delegated conditions

In this puzzle program, the solution must be a signed list of conditions, which
is returned literally.
"""

from __future__ import annotations

from typing import cast

from chia.types.blockchain_format.program import Program

from .load_clvm import load_clvm_maybe_recompile

MOD = load_clvm_maybe_recompile("p2_delegated_conditions.clsp")


def puzzle_for_pk(public_key: Program) -> Program:
    return MOD.curry(public_key)


def solution_for_conditions(conditions: Program) -> Program:
    # TODO: Remove cast when we improve typing
    return cast(Program, conditions.to([conditions]))
