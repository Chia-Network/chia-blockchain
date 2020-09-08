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

from typing import List

from src.types.program import Program

from . import p2_conditions

from .load_clvm import load_clvm


MOD = load_clvm("p2_delegated_puzzle.clvm")


def puzzle_for_pk(public_key: bytes) -> Program:
    return MOD.curry(public_key)


def solution_for_conditions(puzzle_reveal, conditions) -> Program:
    delegated_puzzle = p2_conditions.puzzle_for_conditions(conditions)
    solution: List = []
    return Program.to([puzzle_reveal, [delegated_puzzle, solution]])


def solution_for_delegated_puzzle(puzzle_reveal, delegated_solution) -> Program:
    return Program.to([puzzle_reveal, delegated_solution])
