from __future__ import annotations

from typing import Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.uncurried_puzzle import UncurriedPuzzle
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash, curry_and_treehash

SINGLETON_TOP_LAYER_MOD = load_clvm_maybe_recompile("singleton_top_layer_v1_1.clsp")
SINGLETON_TOP_LAYER_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
SINGLETON_TOP_LAYER_MOD_HASH_QUOTED = calculate_hash_of_quoted_mod_hash(SINGLETON_TOP_LAYER_MOD_HASH)
SINGLETON_LAUNCHER_PUZZLE = load_clvm_maybe_recompile("singleton_launcher.clsp")
SINGLETON_LAUNCHER_PUZZLE_HASH = SINGLETON_LAUNCHER_PUZZLE.get_tree_hash()


def get_inner_puzzle_from_singleton(puzzle: UncurriedPuzzle) -> Optional[Program]:
    """
    Extract the inner puzzle of a singleton
    :param puzzle: Uncurried Singleton puzzle
    :return: Inner puzzle
    """
    if puzzle is None:
        return None

    if not is_singleton(puzzle.mod):
        return None
    singleton_struct, inner_puzzle = list(puzzle.args.as_iter())
    return Program(inner_puzzle)


def get_singleton_id_from_singleton(puzzle: UncurriedPuzzle) -> Optional[bytes32]:
    """
    Extract the singleton_id from the full puzzle of a singleton
    :param puzzle: Uncurried Singleton puzzle
    :return: Singleton ID
    """
    if puzzle is None:
        return None

    if not is_singleton(puzzle.mod):
        return None
    singleton_struct, inner_puzzle = list(puzzle.args.as_iter())
    return bytes32(singleton_struct.at("rf").as_atom())


def is_singleton(inner_f: Program) -> bool:
    """
    Check if a puzzle is a singleton mod
    :param inner_f: puzzle
    :return: Boolean
    """
    return inner_f == SINGLETON_TOP_LAYER_MOD


def create_singleton_puzzle_hash(innerpuz_hash: bytes32, launcher_id: bytes32) -> bytes32:
    """
    Return Hash ID of the whole Singleton Puzzle
    :param innerpuz_hash: Singleton inner puzzle tree hash
    :param launcher_id: launcher coin name
    :return: Singleton full puzzle hash
    """
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_PUZZLE_HASH)))

    return curry_and_treehash(SINGLETON_TOP_LAYER_MOD_HASH_QUOTED, singleton_struct.get_tree_hash(), innerpuz_hash)


def create_singleton_puzzle(innerpuz: Program, launcher_id: bytes32) -> Program:
    """
    Create a full Singleton puzzle
    :param innerpuz: Singleton inner puzzle
    :param launcher_id:
    :return: Singleton full puzzle
    """
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_PUZZLE_HASH)))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, innerpuz)
