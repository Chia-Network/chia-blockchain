"""
Pay to delegated puzzle

In this puzzle program, the solution must be a signed delegated puzzle, along with
its (unsigned) solution. The delegated puzzle is executed, passing in the solution.
This obviously could be done recursively, arbitrarily deep (as long as the maximum
cost is not exceeded).

If you want to specify the conditions directly (thus terminating the potential recursion),
you can use p2_conditions.

This roughly corresponds to bitcoin's graftroot.
"""

from src.types.blockchain_format.program import Program

from . import p2_conditions

from .load_clvm import load_clvm


MOD = load_clvm("p2_delegated_puzzle.clvm")


def puzzle_for_pk(public_key: bytes) -> Program:
    return MOD.curry(public_key)


def solution_for_conditions(conditions) -> Program:
    delegated_puzzle = p2_conditions.puzzle_for_conditions(conditions)
    return solution_for_delegated_puzzle(delegated_puzzle, Program.to(0))


def solution_for_delegated_puzzle(delegated_puzzle: Program, delegated_solution: Program) -> Program:
    return Program.to([delegated_puzzle, delegated_solution])
