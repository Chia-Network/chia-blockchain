"""
Pay to m of n direct

This puzzle program is like p2_delegated_puzzle except instead of one public key,
it includes N public keys, any M of which needs to sign the delegated puzzle.
"""

from __future__ import annotations

from chia.types.blockchain_format.program import Program

from .load_clvm import load_clvm_maybe_recompile

MOD = load_clvm_maybe_recompile("p2_m_of_n_delegate_direct.clvm")


def puzzle_for_m_of_public_key_list(m, public_key_list) -> Program:
    return MOD.curry(m, public_key_list)


def solution_for_delegated_puzzle(m, selectors, puzzle, solution) -> Program:
    return Program.to([selectors, puzzle, solution])
