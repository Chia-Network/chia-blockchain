from __future__ import annotations

from chia_rs import G1Element

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.util.merkle_tree import MerkleTree

# MODS
P2_CONDITIONS_MOD: Program = load_clvm("p2_conditions.clsp")
P2_DELEGATED_SECP_MOD: Program = load_clvm("p2_delegated_secp.clsp")
P2_1_OF_N_MOD: Program = load_clvm("p2_1_of_n.clsp")
P2_1_OF_N_MOD_HASH = P2_1_OF_N_MOD.get_tree_hash()
P2_RECOVERY_MOD: Program = load_clvm("vault_p2_recovery.clsp")
P2_RECOVERY_MOD_HASH = P2_RECOVERY_MOD.get_tree_hash()
RECOVERY_FINISH_MOD: Program = load_clvm("vault_recovery_finish.clsp")
RECOVERY_FINISH_MOD_HASH = RECOVERY_FINISH_MOD.get_tree_hash()


# PUZZLES
def construct_p2_delegated_secp(secp_pk: bytes, genesis_challenge: bytes32) -> Program:
    return P2_DELEGATED_SECP_MOD.curry(genesis_challenge, secp_pk)


def construct_recovery_finish(timelock: uint64, recovery_conditions: Program) -> Program:
    return RECOVERY_FINISH_MOD.curry(timelock, recovery_conditions)


def construct_p2_recovery_puzzle(secp_puzzlehash: bytes32, bls_pk: G1Element, timelock: uint64) -> Program:
    return P2_RECOVERY_MOD.curry(P2_1_OF_N_MOD_HASH, RECOVERY_FINISH_MOD_HASH, secp_puzzlehash, bls_pk, timelock)


def construct_vault_puzzle(secp_puzzlehash: bytes32, recovery_puzzlehash: bytes32) -> Program:
    return P2_1_OF_N_MOD.curry(MerkleTree([secp_puzzlehash, recovery_puzzlehash]).calculate_root())


# MERKLE
def construct_vault_merkle_tree(secp_puzzlehash: bytes32, recovery_puzzlehash: bytes32) -> MerkleTree:
    return MerkleTree([secp_puzzlehash, recovery_puzzlehash])


def get_vault_proof(merkle_tree: MerkleTree, puzzlehash: bytes32) -> Program:
    proof = merkle_tree.generate_proof(puzzlehash)
    vault_proof: Program = Program.to((proof[0], proof[1][0]))
    return vault_proof


# SECP SIGNATURE
def construct_secp_message(delegated_puzzlehash: bytes32, coin_id: bytes32, genesis_challenge: bytes32) -> bytes:
    return delegated_puzzlehash + coin_id + genesis_challenge
