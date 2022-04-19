from clvm_tools.binutils import assemble
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from typing import List, Optional, Tuple, Iterator, Dict
from blspy import G1Element
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.types.condition_opcodes import ConditionOpcode


SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
DID_INNERPUZ_MOD = load_clvm("did_innerpuz.clvm")
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")
SINGLETON_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
LAUNCHER_PUZZLE_HASH = SINGLETON_LAUNCHER.get_tree_hash()
DID_INNERPUZ_MOD_HASH = DID_INNERPUZ_MOD.get_tree_hash()


def create_innerpuz(
    p2_puzzle: Program,
    identities: List[bytes],
    num_of_backup_ids_needed: uint64,
    singleton_id: bytes32,
    metadata: Program = Program.to([]),
) -> Program:
    backup_ids_hash = Program(Program.to(identities)).get_tree_hash()
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    return DID_INNERPUZ_MOD.curry(p2_puzzle, backup_ids_hash, num_of_backup_ids_needed, singleton_struct, metadata)


def get_inner_puzhash_by_p2(
    p2_puzhash: bytes32,
    identities: List[bytes],
    num_of_backup_ids_needed: uint64,
    singleton_id: bytes32,
    metadata: Program = Program.to([]),
) -> bytes32:
    backup_ids_hash = Program(Program.to(identities)).get_tree_hash()
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, LAUNCHER_PUZZLE_HASH)))
    return DID_INNERPUZ_MOD.curry(
        p2_puzhash, backup_ids_hash, num_of_backup_ids_needed, singleton_struct, metadata
    ).get_tree_hash(p2_puzhash)


def create_fullpuz(innerpuz: Program, genesis_id: bytes32) -> Program:
    mod_hash = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((mod_hash, (genesis_id, LAUNCHER_PUZZLE.get_tree_hash())))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, innerpuz)


def is_did_innerpuz(inner_f: Program) -> bool:
    """
    You may want to generalize this if different `CAT_MOD` templates are supported.
    """
    return inner_f == DID_INNERPUZ_MOD


def is_did_core(inner_f: Program) -> bool:
    return inner_f == SINGLETON_TOP_LAYER_MOD


def uncurry_innerpuz(puzzle: Program) -> Optional[Tuple[Program, Program, Program, Program, Program]]:
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    if not is_did_innerpuz(inner_f):
        return None

    p2_puzzle, id_list, num_of_backup_ids_needed, singleton_struct, metadata = list(args.as_iter())
    return p2_puzzle, id_list, num_of_backup_ids_needed, singleton_struct, metadata


def get_innerpuzzle_from_puzzle(puzzle: Program) -> Optional[Program]:
    r = puzzle.uncurry()
    if r is None:
        return None
    inner_f, args = r
    if not is_did_core(inner_f):
        return None
    SINGLETON_STRUCT, INNER_PUZZLE = list(args.as_iter())
    return INNER_PUZZLE


def create_recovery_message_puzzle(recovering_coin_id: bytes32, newpuz: bytes32, pubkey: G1Element) -> Program:
    puzstring = f"(q . ((0x{ConditionOpcode.CREATE_COIN_ANNOUNCEMENT.hex()} 0x{recovering_coin_id.hex()}) (0x{ConditionOpcode.AGG_SIG_UNSAFE.hex()} 0x{bytes(pubkey).hex()} 0x{newpuz.hex()})))"  # noqa
    puz = assemble(puzstring)
    return Program.to(puz)


def create_spend_for_message(
    parent_of_message: bytes32, recovering_coin: bytes32, newpuz: bytes32, pubkey: G1Element
) -> CoinSpend:
    puzzle = create_recovery_message_puzzle(recovering_coin, newpuz, pubkey)
    coin = Coin(parent_of_message, puzzle.get_tree_hash(), uint64(0))
    solution = Program.to([])
    coinsol = CoinSpend(coin, puzzle, solution)
    return coinsol


def match_did_puzzle(puzzle: Program) -> Tuple[bool, Iterator[Program]]:
    """
    Given a puzzle test if it's an DID and, if it is, return the curried arguments
    """
    try:
        mod, curried_args = puzzle.uncurry()
        if mod == SINGLETON_TOP_LAYER_MOD:
            mod, curried_args = curried_args.rest().first().uncurry()
            if mod == DID_INNERPUZ_MOD:
                return True, curried_args.as_iter()
    except Exception:
        import traceback

        print(f"exception: {traceback.format_exc()}")
        return False, iter(())
    return False, iter(())


# inspect puzzle and check it is a DID puzzle
def check_is_did_puzzle(puzzle: Program) -> bool:
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    return is_did_core(inner_f)


def metadata_to_program(metadata: Dict) -> Program:
    """
    Convert the metadata dict to a Chialisp program
    :param metadata: User defined metadata
    :return: Chialisp program
    """
    kv_list = []
    for key, value in metadata.items():
        kv_list.append((assemble(key), assemble(value)))
    return Program.to(kv_list)


def program_to_metadata(program: Program) -> Dict:
    """
    Convert a program to a metadata dict
    :param program: Chialisp program contains the metadata
    :return: Metadata dict
    """
    metadata = {}
    for key, val in program.as_python():
        metadata[str(key, "utf-8")] = str(val, "utf-8")
    return metadata
