from __future__ import annotations

from typing import Optional

from chia_rs import G1Element

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import DEFAULT_HIDDEN_PUZZLE, puzzle_hash_for_pk
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
    puzzle_for_singleton,
    puzzle_hash_for_singleton,
    solution_for_singleton,
)
from chia.wallet.util.merkle_tree import MerkleTree

# MODS
P2_CONDITIONS_MOD: Program = load_clvm("p2_conditions.clsp")
P2_DELEGATED_SECP_MOD: Program = load_clvm("p2_delegated_or_hidden_secp.clsp")
P2_1_OF_N_MOD: Program = load_clvm("p2_1_of_n.clsp")
P2_1_OF_N_MOD_HASH = P2_1_OF_N_MOD.get_tree_hash()
P2_RECOVERY_MOD: Program = load_clvm("vault_p2_recovery.clsp")
P2_RECOVERY_MOD_HASH = P2_RECOVERY_MOD.get_tree_hash()
RECOVERY_FINISH_MOD: Program = load_clvm("vault_recovery_finish.clsp")
RECOVERY_FINISH_MOD_HASH = RECOVERY_FINISH_MOD.get_tree_hash()
P2_SINGLETON_MOD: Program = load_clvm("p2_singleton.clsp")
P2_SINGLETON_MOD_HASH = P2_SINGLETON_MOD.get_tree_hash()


# PUZZLES
def construct_p2_delegated_secp(secp_pk: bytes, genesis_challenge: bytes32, hidden_puzzle_hash: bytes) -> Program:
    return P2_DELEGATED_SECP_MOD.curry(genesis_challenge, secp_pk, hidden_puzzle_hash)


def construct_recovery_finish(timelock: uint64, recovery_conditions: Program) -> Program:
    return RECOVERY_FINISH_MOD.curry(timelock, recovery_conditions)


def construct_vault_puzzle(secp_puzzle_hash: bytes32, recovery_puzzle_hash: Optional[bytes32]) -> Program:
    if recovery_puzzle_hash:
        merkle_root = MerkleTree([secp_puzzle_hash, recovery_puzzle_hash]).calculate_root()
    else:
        merkle_root = MerkleTree([secp_puzzle_hash]).calculate_root()
    return P2_1_OF_N_MOD.curry(merkle_root)


def get_recovery_puzzle(secp_puzzle_hash: bytes32, bls_pk: Optional[G1Element], timelock: Optional[uint64]) -> Program:
    return P2_RECOVERY_MOD.curry(P2_1_OF_N_MOD_HASH, RECOVERY_FINISH_MOD_HASH, secp_puzzle_hash, bls_pk, timelock)


def get_vault_hidden_puzzle_with_index(index: uint32, hidden_puzzle: Program = DEFAULT_HIDDEN_PUZZLE) -> Program:
    hidden_puzzle_with_index: Program = Program.to([6, (index, hidden_puzzle)])
    return hidden_puzzle_with_index


def get_vault_inner_puzzle(
    secp_pk: bytes,
    genesis_challenge: bytes32,
    hidden_puzzle_hash: bytes,
    bls_pk: Optional[G1Element] = None,
    timelock: Optional[uint64] = None,
) -> Program:
    secp_puzzle_hash = construct_p2_delegated_secp(secp_pk, genesis_challenge, hidden_puzzle_hash).get_tree_hash()
    recovery_puzzle_hash = get_recovery_puzzle(secp_puzzle_hash, bls_pk, timelock).get_tree_hash() if bls_pk else None
    vault_inner = construct_vault_puzzle(secp_puzzle_hash, recovery_puzzle_hash)
    return vault_inner


def get_vault_inner_puzzle_hash(
    secp_pk: bytes,
    genesis_challenge: bytes32,
    hidden_puzzle_hash: bytes32,
    bls_pk: Optional[G1Element] = None,
    timelock: Optional[uint64] = None,
) -> bytes32:
    vault_puzzle = get_vault_inner_puzzle(secp_pk, genesis_challenge, hidden_puzzle_hash, bls_pk, timelock)
    vault_puzzle_hash: bytes32 = vault_puzzle.get_tree_hash()
    return vault_puzzle_hash


def get_recovery_inner_puzzle(secp_puzzle_hash: bytes32, recovery_finish_hash: bytes32) -> Program:
    puzzle = construct_vault_puzzle(secp_puzzle_hash, recovery_finish_hash)
    return puzzle


def get_vault_full_puzzle(launcher_id: bytes32, inner_puzzle: Program) -> Program:
    full_puzzle = puzzle_for_singleton(launcher_id, inner_puzzle)
    return full_puzzle


def get_vault_full_puzzle_hash(launcher_id: bytes32, inner_puzzle_hash: bytes32) -> bytes32:
    puzzle_hash = puzzle_hash_for_singleton(launcher_id, inner_puzzle_hash)
    return puzzle_hash


def get_recovery_conditions(bls_pk: G1Element, amount: uint64) -> Program:
    puzzle_hash = puzzle_hash_for_pk(bls_pk)
    recovery_conditions: Program = Program.to([[51, puzzle_hash, amount]])
    return recovery_conditions


def get_recovery_finish_puzzle(bls_pk: G1Element, timelock: uint64, amount: uint64) -> Program:
    recovery_condition = get_recovery_conditions(bls_pk, amount)
    return RECOVERY_FINISH_MOD.curry(timelock, recovery_condition)


def get_p2_singleton_puzzle(launcher_id: bytes32) -> Program:
    puzzle = P2_SINGLETON_MOD.curry(SINGLETON_MOD_HASH, launcher_id, SINGLETON_LAUNCHER_HASH)
    return puzzle


def get_p2_singleton_puzzle_hash(launcher_id: bytes32) -> bytes32:
    return get_p2_singleton_puzzle(launcher_id).get_tree_hash()


def match_vault_puzzle(mod: Program, curried_args: Program) -> bool:
    try:
        if mod == SINGLETON_MOD:
            if curried_args.at("rf").uncurry()[0] == P2_1_OF_N_MOD:
                return True
    except ValueError:
        # We just pass here to prevent spamming logs with error messages when WSM checks incoming coins
        pass
    return False


# SOLUTIONS
def get_recovery_solution(amount: uint64, bls_pk: G1Element) -> Program:
    recovery_conditions = get_recovery_conditions(bls_pk, amount)
    recovery_solution: Program = Program.to([amount, recovery_conditions])
    return recovery_solution


def get_vault_inner_solution(puzzle_to_run: Program, solution: Program, proof: Program) -> Program:
    inner_solution: Program = Program.to([proof, puzzle_to_run, solution])
    return inner_solution


def get_vault_full_solution(lineage_proof: LineageProof, amount: uint64, inner_solution: Program) -> Program:
    full_solution: Program = solution_for_singleton(lineage_proof, amount, inner_solution)
    return full_solution


# MERKLE
def construct_vault_merkle_tree(
    secp_puzzle_hash: bytes32, recovery_puzzle_hash: Optional[bytes32] = None
) -> MerkleTree:
    if recovery_puzzle_hash:
        return MerkleTree([secp_puzzle_hash, recovery_puzzle_hash])
    return MerkleTree([secp_puzzle_hash])


def get_vault_proof(merkle_tree: MerkleTree, puzzle_hash: bytes32) -> Program:
    proof = merkle_tree.generate_proof(puzzle_hash)
    vault_proof: Program = Program.to((proof[0], proof[1][0]))
    return vault_proof


# SECP SIGNATURE
def construct_secp_message(
    delegated_puzzle_hash: bytes32, coin_id: bytes32, genesis_challenge: bytes32, hidden_puzzle_hash: bytes
) -> bytes:
    return delegated_puzzle_hash + coin_id + genesis_challenge + hidden_puzzle_hash
