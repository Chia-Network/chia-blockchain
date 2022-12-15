from typing import Dict, Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.util.curry_and_treehash import curry_and_treehash, calculate_hash_of_quoted_mod_hash


SINGLETON_TOP_LAYER_MOD = load_clvm_maybe_recompile("singleton_top_layer_v1_1.clvm")
SINGLETON_TOP_LAYER_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
SINGLETON_TOP_LAYER_MOD_HASH_QUOTED = calculate_hash_of_quoted_mod_hash(SINGLETON_TOP_LAYER_MOD_HASH)
LAUNCHER_PUZZLE = load_clvm_maybe_recompile("singleton_launcher.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()


def program_to_metadata(program: Program) -> Dict[str, str]:
    """
    Convert a program to a metadata dict
    :param program: Chialisp program contains the metadata
    :return: Metadata dict
    """
    metadata = {}
    for key, val in program.as_python():
        metadata[str(key, "utf-8")] = str(val, "utf-8")
    return metadata


def get_innerpuzzle_from_puzzle(puzzle: Program) -> Optional[Program]:
    """
    Extract the inner puzzle of a singleton
    :param puzzle: Singleton puzzle
    :return: Inner puzzle
    """
    r = puzzle.uncurry()
    if r is None:
        return None
    inner_f, args = r
    if not is_did_core(inner_f):
        return None
    SINGLETON_STRUCT, INNER_PUZZLE = list(args.as_iter())
    return Program(INNER_PUZZLE)


def metadata_to_program(metadata: Dict[str, str]) -> Program:
    """
    Convert the metadata dict to a Chialisp program
    :param metadata: User defined metadata
    :return: Chialisp program
    """
    kv_list = []
    for key, value in metadata.items():
        kv_list.append((key, value))
    return Program(Program.to(kv_list))


def is_did_core(inner_f: Program) -> bool:
    """
    Check if a puzzle is a singleton mod
    :param inner_f: puzzle
    :return: Boolean
    """
    return inner_f == SINGLETON_TOP_LAYER_MOD


def create_fullpuz_hash(innerpuz_hash: bytes32, launcher_id: bytes32) -> bytes32:
    """
    Create a full puzzle of DID
    :param innerpuz_hash: DID inner puzzle tree hash
    :param launcher_id: launcher coin name
    :return: DID full puzzle hash
    """
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (launcher_id, LAUNCHER_PUZZLE_HASH)))

    return curry_and_treehash(SINGLETON_TOP_LAYER_MOD_HASH_QUOTED, singleton_struct.get_tree_hash(), innerpuz_hash)


def create_fullpuz(innerpuz: Program, launcher_id: bytes32) -> Program:
    """
    Create a full puzzle of DID
    :param innerpuz: DID inner puzzle
    :param launcher_id:
    :return: DID full puzzle
    """
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (launcher_id, LAUNCHER_PUZZLE_HASH)))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, innerpuz)
