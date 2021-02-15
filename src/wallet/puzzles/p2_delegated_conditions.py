"""
Pay to delegated conditions

In this puzzle program, the solution must be a signed list of conditions, which
is returned literally.
"""


from src.types.blockchain_format.program import Program

from .load_clvm import load_clvm


MOD = load_clvm("p2_delegated_conditions.clvm")


def puzzle_for_pk(public_key) -> Program:
    return MOD.curry(public_key)


def solution_for_conditions(puzzle_reveal, conditions) -> Program:
    return Program.to([puzzle_reveal, [conditions]])
