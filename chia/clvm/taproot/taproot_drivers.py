from typing import Dict

from chia.clvm.taproot.merkle_tree import MerkleTree
from chia.clvm.load_clvm import load_clvm
from chia.types.blockchain_format.program import Program

TAPROOT_MOD = load_clvm("shared_custody.clsp", package_or_requirement="chia.clvm.taproot.puzzles")


def create_taproot_puzzle(tree: MerkleTree) -> Program:
    return TAPROOT_MOD.curry(
        TAPROOT_MOD.get_tree_hash(),
        tree.calculate_root(),
    )


def create_taproot_solution(tree: MerkleTree, inner_puzzle: Program, inner_solution: Program) -> Program:
    return Program.to(
        [
            Program.to(tree.generate_proof(inner_puzzle.get_tree_hash())),
            inner_puzzle,
            inner_solution,
        ]
    )


def uncurry_taproot_puzzle(puzzle: Program) -> Dict:
    mod, args = puzzle.uncurry()
    mod_hash, merkle_root = args.as_python()
    return {
        "mod_hash": mod_hash,
        "merkle_root": merkle_root,
    }
