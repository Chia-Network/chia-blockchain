"""
Pay to m of n direct

This puzzle program is like p2_delegated_puzzle except instead of one public key,
it includes N public keys, any M of which needs to sign the delegated puzzle.
"""

from __future__ import annotations

from chia_puzzles_py.programs import P2_M_OF_N_DELEGATE_DIRECT

from chia.types.blockchain_format.program import Program

MOD = Program.from_bytes(P2_M_OF_N_DELEGATE_DIRECT)


def puzzle_for_m_of_public_key_list(m, public_key_list) -> Program:
    return MOD.curry(m, public_key_list)


def solution_for_delegated_puzzle(m, selectors, puzzle, solution) -> Program:
    return Program.to([selectors, puzzle, solution])
