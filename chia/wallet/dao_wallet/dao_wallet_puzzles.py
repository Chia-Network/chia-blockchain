from typing import List

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.singleton import SINGLETON_TOP_LAYER_MOD_HASH, LAUNCHER_PUZZLE_HASH
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash, curry_and_treehash


def get_dao_inner_puzhash_by_p2(
    p2_puzzle_hash: bytes32,
    launcher_id: bytes32,
    metadata: Program = Program.to([]),
) -> bytes32:
    """
    Calculate DAO inner puzzle hash from a P2 puzzle hash
    :param p2_puzzle_hash: P2 puzzle hash
    :param launcher_id: ID of the launch coin
    :param metadata: DAO metadata
    :return: DAO inner puzzle hash
    """

    # backup_ids_hash = Program(Program.to(recovery_list)).get_tree_hash()
    # singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (launcher_id, LAUNCHER_PUZZLE_HASH)))
    #
    # quoted_mod_hash = calculate_hash_of_quoted_mod_hash(TREASURY_INNERPUZ_MOD_HASH)
    #
    # return curry_and_treehash(
    #     quoted_mod_hash,
    #     p2_puzzle_hash,
    #     Program.to(backup_ids_hash).get_tree_hash(),
    #     Program.to(num_of_backup_ids_needed).get_tree_hash(),
    #     Program.to(singleton_struct).get_tree_hash(),
    #     metadata.get_tree_hash(),
    # )
    return bytes32(b"0" * 32)
