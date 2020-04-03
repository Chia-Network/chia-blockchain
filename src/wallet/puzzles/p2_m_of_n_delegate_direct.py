"""
Pay to m of n direct

This puzzle program is like p2_delegated_puzzle except instead of one public key,
it includes N public keys, any M of which needs to sign the delegated puzzle.
"""

from src.types.program import Program
from clvm_tools import binutils

from .load_clvm import load_clvm


puzzle_prog_template = load_clvm("make_puzzle_m_of_n_direct.clvm")


def puzzle_for_m_of_public_key_list(m, public_key_list):
    format_tuple = tuple(
        [
            binutils.disassemble(Program.to(_))
            for _ in (puzzle_prog_template, m, public_key_list)
        ]
    )
    puzzle_src = "((c (q %s) (c (q %s) (c (q %s) (a)))))" % (
        format_tuple[0],
        format_tuple[1],
        format_tuple[2],
    )
    puzzle_prog = binutils.assemble(puzzle_src)
    return Program.to(puzzle_prog)


def solution_for_delegated_puzzle(m, public_key_list, selectors, puzzle, solution):
    puzzle_reveal = puzzle_for_m_of_public_key_list(m, public_key_list)
    return Program.to([puzzle_reveal, [selectors, puzzle, solution]])
