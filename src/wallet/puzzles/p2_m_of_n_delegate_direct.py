"""
Pay to m of n direct

This puzzle program is like p2_delegated_puzzle except instead of one public key,
it includes N public keys, any M of which needs to sign the delegated puzzle.
"""

from src.types.blockchain_format.program import Program

from .load_clvm import load_clvm


MOD = load_clvm("p2_m_of_n_delegate_direct.clvm")


def puzzle_for_m_of_public_key_list(m, public_key_list) -> Program:
    return MOD.curry(m, public_key_list)


def solution_for_delegated_puzzle(m, public_key_list, selectors, puzzle, solution) -> Program:
    puzzle_reveal = puzzle_for_m_of_public_key_list(m, public_key_list)
    return Program.to([puzzle_reveal, [selectors, puzzle, solution]])
