from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm

# from chia.types.condition_opcodes import ConditionOpcode
# from chia.wallet.util.merkle_tree import MerkleTree, TreeType


SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")
DB_HOST_MOD = load_clvm("database_layer.clvm")
DB_OFFER_MOD = load_clvm("database_offer.clvm")

DB_HOST_MOD_HASH = DB_HOST_MOD.get_tree_hash()


def create_host_fullpuz(innerpuz: Program, current_root: bytes32, genesis_id: bytes32) -> Program:
    mod_hash = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((mod_hash, (genesis_id, SINGLETON_LAUNCHER.get_tree_hash())))
    db_layer = DB_HOST_MOD.curry(DB_HOST_MOD.get_tree_hash(), current_root, innerpuz)
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, db_layer)


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
