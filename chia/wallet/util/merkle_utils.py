from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

from chia.types.blockchain_format.sized_bytes import bytes32

TupleTree = Any  # Union[bytes32, Tuple["TupleTree", "TupleTree"]]
Proof_Tree_Type = Any  # Union[bytes32, Tuple[bytes32, "Proof_Tree_Type"]]


HASH_TREE_PREFIX = bytes([2])
HASH_LEAF_PREFIX = bytes([1])

# paths here are not quite the same a `NodePath` paths. We don't need the high order bit
# anymore since the proof indicates how big the path is.


def compose_paths(path_1: int, path_2: int, path_2_length: int) -> int:
    return (path_1 << path_2_length) | path_2


def sha256(*args: bytes) -> bytes32:
    return bytes32(hashlib.sha256(b"".join(args)).digest())


def build_merkle_tree_from_binary_tree(tuples: TupleTree) -> Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]]:
    if isinstance(tuples, bytes):
        tuples = bytes32(tuples)
        return sha256(HASH_LEAF_PREFIX, tuples), {tuples: (0, [])}

    left, right = tuples
    left_root, left_proofs = build_merkle_tree_from_binary_tree(left)
    right_root, right_proofs = build_merkle_tree_from_binary_tree(right)

    new_root = sha256(HASH_TREE_PREFIX, left_root, right_root)
    new_proofs = {}
    for name, (path, proof) in left_proofs.items():
        proof.append(right_root)
        new_proofs[name] = (path, proof)
    for name, (path, proof) in right_proofs.items():
        path |= 1 << len(proof)
        proof.append(left_root)
        new_proofs[name] = (path, proof)
    return new_root, new_proofs


def list_to_binary_tree(objects: List[Any]) -> Any:
    size = len(objects)
    if size == 1:
        return objects[0]
    midpoint = (size + 1) >> 1
    first_half = objects[:midpoint]
    last_half = objects[midpoint:]
    return (list_to_binary_tree(first_half), list_to_binary_tree(last_half))


def build_merkle_tree(objects: List[bytes32]) -> Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]]:
    """
    return (merkle_root, dict_of_proofs)
    """
    objects_binary_tree = list_to_binary_tree(objects)
    return build_merkle_tree_from_binary_tree(objects_binary_tree)


def merkle_proof_from_path_and_tree(node_path: int, proof_tree: Proof_Tree_Type) -> Tuple[int, List[bytes32]]:
    proof_path = 0
    proof = []
    while not isinstance(proof_tree, bytes32):
        left_vs_right = node_path & 1
        path_element = proof_tree[1][1 - left_vs_right]
        if isinstance(path_element, bytes32):
            proof.append(path_element)
        else:
            proof.append(path_element[0])
        node_path >>= 1
        proof_tree = proof_tree[1][left_vs_right]
        proof_path += proof_path + left_vs_right
    proof.reverse()
    return proof_path, proof


def _simplify_merkle_proof(tree_hash: bytes32, proof: Tuple[int, List[bytes32]]) -> bytes32:
    # we return the expected merkle root
    path, nodes = proof
    for node in nodes:
        if path & 1:
            tree_hash = sha256(HASH_TREE_PREFIX, node, tree_hash)
        else:
            tree_hash = sha256(HASH_TREE_PREFIX, tree_hash, node)
        path >>= 1
    return tree_hash


def simplify_merkle_proof(tree_hash: bytes32, proof: Tuple[int, List[bytes32]]) -> bytes32:
    return _simplify_merkle_proof(sha256(HASH_LEAF_PREFIX, tree_hash), proof)


def check_merkle_proof(merkle_root: bytes32, tree_hash: bytes32, proof: Tuple[int, List[bytes32]]) -> bool:
    return merkle_root == simplify_merkle_proof(tree_hash, proof)
