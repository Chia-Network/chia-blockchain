"""
Pay to puzzle hash

In this puzzle program, the solution must be a reveal of the puzzle with the given
hash along with its solution.
"""

from clvm_tools import binutils

from src.types.program import Program

"""
solution: (puzzle_reveal . solution_to_puzzle)

(if (= (sha256 (wrap puzzle_reveal)) puzzle_hash) ((c puzzle_reveal solution_to_puzzle (a))) (x))

((c (i (= (sha256 (wrap puzzle_reveal)) puzzle_hash) (q (e (f (a)) (r (a)))) (q (x))) (a)))

((c (i (= (sha256 (wrap (f (a)))) CONST) (q (e (f (a)) (r (a)))) (q (x))) (a)))
"""


def puzzle_for_puzzle_hash(underlying_puzzle_hash):
    TEMPLATE = "((c (i (= (sha256tree (f (a))) (q 0x%s)) (q ((c (f (a)) (f (r (a)))))) (q (x))) (a)))"
    return Program.to(binutils.assemble(TEMPLATE % underlying_puzzle_hash.hex()))


def solution_for_puzzle_and_solution(underlying_puzzle, underlying_solution):
    underlying_puzzle_hash = underlying_puzzle.get_hash()
    puzzle_program = puzzle_for_puzzle_hash(underlying_puzzle_hash)
    return Program.to([puzzle_program, underlying_solution])
