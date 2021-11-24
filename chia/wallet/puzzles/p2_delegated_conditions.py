"""
Pay to delegated conditions

In this puzzle program, the solution must be a signed list of conditions, which
is returned literally.
"""


from chia.types.blockchain_format.program import Program

from .load_clvm import load_clvm

MOD = load_clvm("p2_delegated_conditions.clvm")


def puzzle_for_pk(public_key: Program) -> Program:
    return MOD.curry(public_key)


def solution_for_conditions(conditions: Program) -> Program:
    return conditions.to([conditions])
