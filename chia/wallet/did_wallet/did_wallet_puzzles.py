from clvm_tools import binutils
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from typing import List, Optional, Tuple
from blspy import G1Element
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_solution import CoinSolution
from chia.util.ints import uint64
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.types.condition_opcodes import ConditionOpcode

DID_CORE_MOD = load_clvm("singleton_top_layer.clvm")
DID_INNERPUZ_MOD = load_clvm("did_innerpuz.clvm")


def create_innerpuz(pubkey: bytes, identities: List[bytes], num_of_backup_ids_needed: uint64) -> Program:
    backup_ids_hash = Program(Program.to(identities)).get_tree_hash()
    return DID_INNERPUZ_MOD.curry(DID_CORE_MOD.get_tree_hash(), pubkey, backup_ids_hash, num_of_backup_ids_needed)


def create_fullpuz(innerpuz, genesis_id) -> Program:
    mod_hash = DID_CORE_MOD.get_tree_hash()
    return DID_CORE_MOD.curry(mod_hash, genesis_id, innerpuz)


def fullpuz_hash_for_inner_puzzle_hash(mod_code, genesis_id, inner_puzzle_hash) -> bytes32:
    """
    Given an inner puzzle hash, calculate a puzzle program hash for a specific cc.
    """
    gid_hash = genesis_id.get_tree_hash()
    return mod_code.curry(mod_code.get_tree_hash(), gid_hash, inner_puzzle_hash).get_tree_hash(
        gid_hash, inner_puzzle_hash
    )


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
    return inner_f == DID_CORE_MOD


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

    core_mod, pubkey, id_list, num_of_backup_ids_needed = list(args.as_iter())
    return pubkey, id_list


def get_innerpuzzle_from_puzzle(puzzle: Program) -> Optional[Program]:
    r = puzzle.uncurry()
    if r is None:
        return None
    inner_f, args = r
    if not is_did_core(inner_f):
        return None
    mod_hash, genesis_id, inner_puzzle = list(args.as_iter())
    return inner_puzzle


def create_recovery_message_puzzle(recovering_coin: bytes32, newpuz: bytes32, pubkey: G1Element):
    puzstring = f"(q . ((0x{ConditionOpcode.CREATE_ANNOUNCEMENT_WITH_ID.hex()} 0x{recovering_coin.hex()}) (0x{ConditionOpcode.AGG_SIG.hex()} 0x{bytes(pubkey).hex()} 0x{newpuz.hex()})))"  # noqa
    puz = binutils.assemble(puzstring)
    return Program.to(puz)


def create_spend_for_message(parent_of_message, recovering_coin, newpuz, pubkey):
    puzzle = create_recovery_message_puzzle(recovering_coin, newpuz, pubkey)
    coin = Coin(parent_of_message, puzzle.get_tree_hash(), uint64(0))
    solution = Program.to([])
    coinsol = CoinSolution(coin, puzzle, solution)
    return coinsol


# inspect puzzle and check it is a CC puzzle
def check_is_did_puzzle(puzzle: Program):
    r = puzzle.uncurry()
    if r is None:
        return r
    inner_f, args = r
    return is_did_core(inner_f)
