"""
Pay to puzzle hash

In this puzzle program, the solution must be a reveal of the puzzle with the given
hash along with its solution.
"""

from __future__ import annotations

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32

from .load_clvm import load_clvm_maybe_recompile

MOD = load_clvm_maybe_recompile("p2_puzzle_hash.clsp")


def puzzle_for_inner_puzzle_hash(inner_puzzle_hash: bytes32) -> Program:
    program = MOD.curry(inner_puzzle_hash)
    return program


def puzzle_for_inner_puzzle(inner_puzzle: Program) -> Program:
    return puzzle_for_inner_puzzle_hash(inner_puzzle.get_tree_hash())


def solution_for_inner_puzzle_and_inner_solution(inner_puzzle: Program, inner_puzzle_solution: Program) -> Program:
    return Program.to([inner_puzzle, inner_puzzle_solution])
