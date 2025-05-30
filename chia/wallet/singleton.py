from __future__ import annotations

from typing import Optional, Union

from chia_puzzles_py.programs import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_TOP_LAYER_V1_1,
    SINGLETON_TOP_LAYER_V1_1_HASH,
)
from chia_rs import CoinSpend
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, uncurry
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.wallet.util.compute_additions import compute_additions
from chia.wallet.util.curry_and_treehash import (
    calculate_hash_of_quoted_mod_hash,
    curry_and_treehash,
    shatree_atom,
    shatree_pair,
)

SINGLETON_TOP_LAYER_MOD = Program.from_bytes(SINGLETON_TOP_LAYER_V1_1)
SINGLETON_TOP_LAYER_MOD_HASH = bytes32(SINGLETON_TOP_LAYER_V1_1_HASH)
SINGLETON_TOP_LAYER_MOD_HASH_TREE_HASH = shatree_atom(SINGLETON_TOP_LAYER_MOD_HASH)
SINGLETON_TOP_LAYER_MOD_HASH_QUOTED = calculate_hash_of_quoted_mod_hash(SINGLETON_TOP_LAYER_MOD_HASH)
SINGLETON_LAUNCHER_PUZZLE = Program.from_bytes(SINGLETON_LAUNCHER)
SINGLETON_LAUNCHER_PUZZLE_HASH = bytes32(SINGLETON_LAUNCHER_HASH)
SINGLETON_LAUNCHER_PUZZLE_HASH_TREE_HASH = shatree_atom(SINGLETON_LAUNCHER_PUZZLE_HASH)


def get_inner_puzzle_from_singleton(puzzle: Union[Program, SerializedProgram]) -> Optional[Program]:
    """
    Extract the inner puzzle of a singleton
    :param puzzle: Singleton puzzle
    :return: Inner puzzle
    """
    r = uncurry(puzzle)
    if r is None:
        return None
    inner_f, args = r
    if not is_singleton(inner_f):
        return None
    _SINGLETON_STRUCT, INNER_PUZZLE = list(args.as_iter())
    return Program(INNER_PUZZLE)


def get_singleton_id_from_puzzle(puzzle: Union[Program, SerializedProgram]) -> Optional[bytes32]:
    """
    Extract the singleton ID from a singleton puzzle
    :param puzzle: Singleton puzzle
    :return: Inner puzzle
    """
    r = uncurry(puzzle)
    if r is None:
        return None  # pragma: no cover
    inner_f, args = r
    if not is_singleton(inner_f):
        return None
    SINGLETON_STRUCT, _INNER_PUZZLE = list(args.as_iter())
    return bytes32(Program(SINGLETON_STRUCT).rest().first().as_atom())


def is_singleton(inner_f: Union[Program, SerializedProgram]) -> bool:
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
    singleton_struct = shatree_pair(
        SINGLETON_TOP_LAYER_MOD_HASH_TREE_HASH,
        shatree_pair(shatree_atom(launcher_id), SINGLETON_LAUNCHER_PUZZLE_HASH_TREE_HASH),
    )

    return curry_and_treehash(SINGLETON_TOP_LAYER_MOD_HASH_QUOTED, singleton_struct, innerpuz_hash)


def create_singleton_puzzle(innerpuz: Union[Program, SerializedProgram], launcher_id: bytes32) -> Program:
    """
    Create a full Singleton puzzle
    :param innerpuz: Singleton inner puzzle
    :param launcher_id:
    :return: Singleton full puzzle
    """
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_PUZZLE_HASH)))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, innerpuz)


def get_most_recent_singleton_coin_from_coin_spend(coin_sol: CoinSpend) -> Optional[Coin]:
    additions: list[Coin] = compute_additions(coin_sol)
    for coin in additions:
        if coin.amount % 2 == 1:
            return coin
    return None  # pragma: no cover


def get_singleton_struct_for_id(id: bytes32) -> Program:
    singleton_struct: Program = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (id, SINGLETON_LAUNCHER_PUZZLE_HASH)))
    return singleton_struct
