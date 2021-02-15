"""
Pay to puzzle hash

In this puzzle program, the solution must be a reveal of the puzzle with the given
hash along with its solution.
"""

from src.types.blockchain_format.program import Program

from .load_clvm import load_clvm


MOD = load_clvm("p2_puzzle_hash.clvm")


def puzzle_for_puzzle_hash(inner_puzzle_hash) -> Program:
    program = MOD.curry(inner_puzzle_hash)
    return program


def solution_for_puzzle_and_solution(inner_puzzle, inner_puzzle_solution) -> Program:
    inner_puzzle_hash = Program.to(inner_puzzle).tree_hash()
    puzzle_reveal = puzzle_for_puzzle_hash(inner_puzzle_hash)
    return Program.to([puzzle_reveal, inner_puzzle_solution])
