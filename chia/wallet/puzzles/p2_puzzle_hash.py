"""
Pay to puzzle hash

In this puzzle program, the solution must be a reveal of the puzzle with the given
hash along with its solution.
"""

from __future__ import annotations

from chia_puzzles_py.programs import P2_PUZZLE_HASH
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program

MOD = Program.from_bytes(P2_PUZZLE_HASH)


def puzzle_for_inner_puzzle_hash(inner_puzzle_hash: bytes32) -> Program:
    program = MOD.curry(inner_puzzle_hash)
    return program


def puzzle_for_inner_puzzle(inner_puzzle: Program) -> Program:
    return puzzle_for_inner_puzzle_hash(inner_puzzle.get_tree_hash())


def solution_for_inner_puzzle_and_inner_solution(inner_puzzle: Program, inner_puzzle_solution: Program) -> Program:
    return Program.to([inner_puzzle, inner_puzzle_solution])
