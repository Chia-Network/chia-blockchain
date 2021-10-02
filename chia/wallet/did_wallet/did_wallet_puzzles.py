from clvm_tools import binutils
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from typing import List, Optional, Tuple
from blspy import G1Element
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.types.condition_opcodes import ConditionOpcode


SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
DID_INNERPUZ_MOD = load_clvm("did_innerpuz.clvm")
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")


def create_innerpuz(pubkey: bytes, identities: List[bytes], num_of_backup_ids_needed: uint64) -> Program:
    backup_ids_hash = Program(Program.to(identities)).get_tree_hash()
    # MOD_HASH MY_PUBKEY RECOVERY_DID_LIST_HASH NUM_VERIFICATIONS_REQUIRED
    return DID_INNERPUZ_MOD.curry(pubkey, backup_ids_hash, num_of_backup_ids_needed)


def create_fullpuz(innerpuz: Program, genesis_id: bytes32) -> Program:
    mod_hash = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((mod_hash, (genesis_id, LAUNCHER_PUZZLE.get_tree_hash())))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, innerpuz)


def get_pubkey_from_innerpuz(innerpuz: Program) -> G1Element:
    ret = uncurry_innerpuz(innerpuz)
    if ret is not None:
        pubkey_program = ret[0]
    else:
        raise ValueError("Unable to extract pubkey")
    pubkey = G1Element.from_bytes(pubkey_program.as_atom())
    return pubkey


def is_did_innerpuz(inner_f: Program):
    """
    You may want to generalize this if different `CC_MOD` templates are supported.
    """
    return inner_f == DID_INNERPUZ_MOD


def is_did_core(inner_f: Program):
    return inner_f == SINGLETON_TOP_LAYER_MOD


def uncurry_innerpuz(puzzle: Program) -> Optional[Tuple[Program, Program]]:
    """
    Take a puzzle and return `None` if it's not a `CC_MOD` cc, or
    a triple of `mod_hash, genesis_coin_checker, inner_puzzle` if it is.
    """
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    if not is_did_innerpuz(inner_f):
        return None

    pubkey, id_list, num_of_backup_ids_needed = list(args.as_iter())
    return pubkey, id_list


def get_innerpuzzle_from_puzzle(puzzle: Program) -> Optional[Program]:
    r = puzzle.uncurry()
    if r is None:
        return None
    inner_f, args = r
    if not is_did_core(inner_f):
        return None
    SINGLETON_STRUCT, INNER_PUZZLE = list(args.as_iter())
    return INNER_PUZZLE


def create_recovery_message_puzzle(recovering_coin_id: bytes32, newpuz: bytes32, pubkey: G1Element):
    puzstring = f"(q . ((0x{ConditionOpcode.CREATE_COIN_ANNOUNCEMENT.hex()} 0x{recovering_coin_id.hex()}) (0x{ConditionOpcode.AGG_SIG_UNSAFE.hex()} 0x{bytes(pubkey).hex()} 0x{newpuz.hex()})))"  # noqa
    puz = binutils.assemble(puzstring)
    return Program.to(puz)


def create_spend_for_message(parent_of_message, recovering_coin, newpuz, pubkey):
    puzzle = create_recovery_message_puzzle(recovering_coin, newpuz, pubkey)
    coin = Coin(parent_of_message, puzzle.get_tree_hash(), uint64(0))
    solution = Program.to([])
    coinsol = CoinSpend(coin, puzzle, solution)
    return coinsol


# inspect puzzle and check it is a DID puzzle
def check_is_did_puzzle(puzzle: Program):
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    return is_did_core(inner_f)
