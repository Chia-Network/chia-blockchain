from __future__ import annotations
from typing import Any, Dict, List, Tuple

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.util.merkle_utils import build_merkle_tree

from .load_clvm import load_clvm_maybe_recompile

P2_1_OF_N = load_clvm_maybe_recompile("p2_1_of_n.clsp")
P2_CURRIED_PUZZLE_HASH = load_clvm_maybe_recompile("p2_puzzle_hash.clvm")
AUGMENTED_CONDITION = load_clvm_maybe_recompile("augmented_condition.clsp")


def create_augmented_cond_puzzle(condition: List[Any], puzzle_hash: bytes32) -> Program:
    return AUGMENTED_CONDITION.curry(condition, puzzle_hash)

def create_augmented_cond_solution(inner_puzzle: Program, inner_solution: Program) -> Program:
    return Program.to([inner_puzzle, inner_solution])
    
def create_p2_puzzle_hash_puzzle(puzzle_hash: bytes32) -> Program:
    return P2_CURRIED_PUZZLE_HASH.curry(puzzle_hash)

def create_p2_puzzle_hash_solution(inner_puzzle: Program, inner_solution: Program) -> Program:
    return Program.to([inner_puzzle, inner_solution])

def create_clawback_merkle_tree(timelock: uint64, sender_ph: bytes32, recipient_ph: bytes32) -> Program:
    timelock_condition = [80, timelock]
    augmented_cond_puz = create_augmented_cond_puzzle(timelock_condition, recipient_ph)
    p2_puzzle_hash_puz = create_p2_puzzle_hash_puzzle(sender_ph)
    merkle_tree = build_merkle_tree([augmented_cond_puz.get_tree_hash(), p2_puzzle_hash_puz.get_tree_hash()])
    return merkle_tree

def create_merkle_proof(merkle_tree, puzzle_hash: bytes32):
    return Program.to(merkle_tree[1][puzzle_hash])

def create_clawback_puzzle(timelock: uint64, sender_ph: bytes32, recipient_ph: bytes32) -> Program:
    merkle_tree = create_clawback_merkle_tree(timelock, sender_ph, recipient_ph)
    return P2_1_OF_N.curry(merkle_tree[0])

def create_sender_solution(
    timelock: uint64,
    sender_ph: bytes32,
    recipient_ph: bytes32,
    inner_puzzle: Program,
    inner_solution: Program,
) -> Program:
    merkle_tree = create_clawback_merkle_tree(timelock, sender_ph, recipient_ph)
    if inner_puzzle.get_tree_hash() == sender_ph:
        cb_inner_puz = create_p2_puzzle_hash_puzzle(sender_ph)
        merkle_proof = create_merkle_proof(merkle_tree, cb_inner_puz.get_tree_hash())
        cb_inner_solution = create_p2_puzzle_hash_solution(inner_puzzle, inner_solution)
    elif inner_puzzle.get_tree_hash() == recipient_ph:
        condition = [80, timelock]
        cb_inner_puz = create_augmented_cond_puzzle(condition, recipient_ph)
        merkle_proof = create_merkle_proof(merkle_tree, cb_inner_puz.get_tree_hash())
        cb_inner_solution = create_augmented_cond_solution(inner_puzzle, inner_solution)
    return Program.to([merkle_proof, cb_inner_puz, cb_inner_solution])
