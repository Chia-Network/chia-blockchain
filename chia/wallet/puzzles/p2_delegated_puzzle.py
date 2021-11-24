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

from chia.types.blockchain_format.program import Program

from . import p2_conditions
from .load_clvm import load_clvm

MOD = load_clvm("p2_delegated_puzzle.clvm")


def puzzle_for_pk(public_key: bytes) -> Program:
    return MOD.curry(public_key)


def solution_for_conditions(conditions) -> Program:
    delegated_puzzle = p2_conditions.puzzle_for_conditions(conditions)
    # TODO: address hint error and remove ignore
    #       error: Argument 2 to "solution_for_delegated_puzzle" has incompatible type "SExp"; expected "Program"
    #       [arg-type]
    return solution_for_delegated_puzzle(delegated_puzzle, Program.to(0))  # type: ignore[arg-type]


def solution_for_delegated_puzzle(delegated_puzzle: Program, delegated_solution: Program) -> Program:
    # TODO: address hint error and remove ignore
    #       error: Incompatible return value type (got "SExp", expected "Program")  [return-value]
    return delegated_puzzle.to([delegated_puzzle, delegated_solution])  # type: ignore[return-value]
