from typing import Tuple, Iterator

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm

# from chia.types.condition_opcodes import ConditionOpcode
# from chia.wallet.util.merkle_tree import MerkleTree, TreeType


SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
# TODO: need new data layer specific clvm
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")
DB_HOST_MOD = load_clvm("database_layer.clvm")
DB_OFFER_MOD = load_clvm("database_offer.clvm")

DB_HOST_MOD_HASH = DB_HOST_MOD.get_tree_hash()


def create_host_fullpuz(innerpuz_hash: bytes32, current_root: bytes32, genesis_id: bytes32) -> Program:
    db_layer = create_host_layer_puzzle(innerpuz_hash, current_root)
    mod_hash = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
    singleton_struct = Program.to((mod_hash, (genesis_id, SINGLETON_LAUNCHER.get_tree_hash())))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, db_layer)


def create_host_layer_puzzle(innerpuz_hash: bytes32, current_root: bytes32) -> Program:
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    db_layer = DB_HOST_MOD.curry(DB_HOST_MOD.get_tree_hash(), current_root, innerpuz_hash)
    return db_layer


def create_singleton_fullpuz(singleton_id: bytes32, db_layer_puz: Program) -> Program:
    mod_hash = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
    singleton_struct = Program.to((mod_hash, (singleton_id, SINGLETON_LAUNCHER.get_tree_hash())))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, db_layer_puz)


def create_offer_fullpuz(
    leaf_reveal: bytes,
    host_genesis_id: bytes32,
    claim_target: bytes32,
    recovery_target: bytes32,
    recovery_timelock: uint64,
) -> Program:
    mod_hash = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((mod_hash, (host_genesis_id, SINGLETON_LAUNCHER.get_tree_hash())))
    full_puz = DB_OFFER_MOD.curry(
        DB_HOST_MOD_HASH, singleton_struct, leaf_reveal, claim_target, recovery_target, recovery_timelock
    )
    return full_puz


def match_dl_singleton(puzzle: Program) -> Tuple[bool, Iterator[Program]]:
    """
    Given a puzzle test if it's a CAT and, if it is, return the curried arguments
    """
    mod, singleton_curried_args = puzzle.uncurry()
    if mod == SINGLETON_TOP_LAYER_MOD:
        mod, dl_curried_args = singleton_curried_args.at("rf").uncurry()
        if mod == DB_HOST_MOD:
            launcher_id = singleton_curried_args.at("frf")
            root = dl_curried_args.at("rf")
            innerpuz_hash = dl_curried_args.at("rrf")
            return True, iter((innerpuz_hash, root, launcher_id))

    return False, iter(())


def launch_solution_to_singleton_info(launch_solution: Program) -> Tuple[bytes32, uint64, bytes32, bytes32]:
    solution = launch_solution.as_python()
    try:
        full_puzzle_hash = bytes32(solution[0])
        amount = uint64(int.from_bytes(solution[1], "big"))
        root = bytes32(solution[2][0])
        inner_puzzle_hash = bytes32(solution[2][1])
    except (IndexError, TypeError):
        raise ValueError("Launcher is not a data layer launcher")

    return full_puzzle_hash, amount, root, inner_puzzle_hash
