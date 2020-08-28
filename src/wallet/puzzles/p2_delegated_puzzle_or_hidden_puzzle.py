"""
Pay to delegated puzzle or hidden puzzle

In this puzzle program, the solution must choose either a hidden puzzle or a
delegated puzzle on a given public key.

The given public key is morphed by adding an offset from the hash of the hidden puzzle
and itself, giving a new so-called "synthetic" public key which has the hidden puzzle
hidden inside of it.

If the hidden puzzle path is taken, the hidden puzzle and original public key will be revealed
which proves that it was hidden there in the first place.

This roughly corresponds to bitcoin's taproot.
"""
import hashlib

from clvm.casts import int_from_bytes

from src.types.program import Program

from .load_clvm import load_clvm

DEFAULT_HIDDEN_PUZZLE = Program.from_bytes(bytes.fromhex("ff0980"))  # (x)

MOD = load_clvm("p2_delegated_puzzle_or_hidden_puzzle.clvm")

SYNTHETIC_MOD = load_clvm("calculate_synthetic_public_key.clvm")


def calculate_synthetic_offset(public_key, hidden_puzzle_hash) -> int:
    blob = hashlib.sha256(bytes(public_key) + hidden_puzzle_hash).digest()
    return int_from_bytes(blob)


def calculate_synthetic_public_key(public_key, hidden_puzzle) -> Program:
    r = SYNTHETIC_MOD.run([public_key, hidden_puzzle.tree_hash()])
    return r


def puzzle_for_synthetic_public_key(synthetic_public_key) -> Program:
    return MOD.curry(synthetic_public_key)


def puzzle_for_public_key_and_hidden_puzzle(
    public_key, hidden_puzzle=DEFAULT_HIDDEN_PUZZLE
) -> Program:
    synthetic_public_key = calculate_synthetic_public_key(public_key, hidden_puzzle)

    return puzzle_for_synthetic_public_key(synthetic_public_key)


def solution_with_delegated_puzzle(synthetic_public_key, delegated_puzzle, solution) -> Program:
    puzzle = puzzle_for_synthetic_public_key(synthetic_public_key)
    return Program.to([puzzle, [[], delegated_puzzle, solution]])


def solution_with_hidden_puzzle(
    hidden_public_key, hidden_puzzle, solution_to_hidden_puzzle
) -> Program:
    synthetic_public_key = calculate_synthetic_public_key(
        hidden_public_key, hidden_puzzle
    )
    puzzle = puzzle_for_synthetic_public_key(synthetic_public_key)
    return Program.to(
        [puzzle, [hidden_public_key, hidden_puzzle, solution_to_hidden_puzzle]]
    )
