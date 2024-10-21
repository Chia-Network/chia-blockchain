from __future__ import annotations

from typing import Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.conditions import CreatePuzzleAnnouncement
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_LAUNCHER_HASH, SINGLETON_MOD_HASH
from chia.wallet.util.curry_and_treehash import curry_and_treehash, shatree_atom, shatree_pair

PUZZLE = load_clvm("p2_singleton_via_delegated_puzzle_safe.clsp")
PUZZLE_HASH = PUZZLE.get_tree_hash()
QUOTED_PUZZLE = Program.to((1, PUZZLE))
QUOTED_PUZZLE_HASH = QUOTED_PUZZLE.get_tree_hash()
PRE_HASHED_HASHES: dict[bytes32, bytes32] = {
    SINGLETON_MOD_HASH: shatree_atom(SINGLETON_MOD_HASH),
    SINGLETON_LAUNCHER_HASH: shatree_atom(SINGLETON_LAUNCHER_HASH),
}


def _treehash_hash(atom_hash: bytes32) -> bytes32:
    if atom_hash in PRE_HASHED_HASHES:
        return PRE_HASHED_HASHES[atom_hash]
    else:
        return shatree_atom(atom_hash)


def _struct_hash(singleton_mod_hash: bytes32, launcher_id: bytes32, singleton_launcher_hash: bytes32) -> bytes32:
    return shatree_pair(
        _treehash_hash(singleton_mod_hash),
        shatree_pair(_treehash_hash(launcher_id), _treehash_hash(singleton_launcher_hash)),
    )


def match(potential_match: Program) -> Optional[Program]:
    mod, args = potential_match.uncurry()
    if mod == PUZZLE:
        return args
    else:
        return None


def construct(
    launcher_id: bytes32,
    singleton_mod_hash: bytes32 = SINGLETON_MOD_HASH,
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_HASH,
) -> Program:
    return PUZZLE.curry(
        singleton_mod_hash,
        _struct_hash(singleton_mod_hash, launcher_id, singleton_launcher_hash),
    )


def construct_hash(
    launcher_id: bytes32,
    singleton_mod_hash: bytes32 = SINGLETON_MOD_HASH,
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_HASH,
) -> bytes32:
    return curry_and_treehash(
        QUOTED_PUZZLE_HASH,
        _treehash_hash(singleton_mod_hash),
        shatree_atom(_struct_hash(singleton_mod_hash, launcher_id, singleton_launcher_hash)),
    )


def solve(
    singleton_inner_puzhash: bytes32, delegated_puzzle: Program, delegated_solution: Program, my_id: bytes32
) -> Program:
    return Program.to([singleton_inner_puzhash, delegated_puzzle, delegated_solution, my_id])


def required_announcement(delegated_puzzle_hash: bytes32, my_id: bytes32) -> CreatePuzzleAnnouncement:
    return CreatePuzzleAnnouncement(Program.to([my_id, delegated_puzzle_hash]).get_tree_hash())
