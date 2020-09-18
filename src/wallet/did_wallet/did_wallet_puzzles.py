from src.types.sized_bytes import bytes32
from src.types.program import Program
from typing import List, Optional, Tuple
from blspy import G1Element
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.util.ints import uint64
from src.wallet.puzzles.load_clvm import load_clvm
from clvm_tools.curry import curry as ct_curry, uncurry
import string
import clvm

DID_CORE_MOD = load_clvm("did_core.clvm")
DID_INNERPUZ_MOD = load_clvm("did_innerpuz.clvm")
DID_RECOVERY_MESSAGE_MOD = load_clvm("did_recovery_message.clvm")
DID_GROUP_MOD = load_clvm("did_groups.clvm")

# NULL_F = Program.from_bytes(bytes.fromhex("ff01ff8080"))  # (q ())


def curry(*args, **kwargs):
    """
    The clvm_tools version of curry returns `cost, program` for now.
    Eventually it will just return `program`. This placeholder awaits that day.
    """
    cost, prog = ct_curry(*args, **kwargs)
    return Program.to(prog)


def create_innerpuz(pubkey: bytes, identities: List[bytes]) -> Program:
    id_list = []
    for id in identities:
        id_list.append(id)
    return curry(DID_INNERPUZ_MOD, [DID_CORE_MOD, pubkey, id_list])


# def create_fullpuz(innerpuzhash, core) -> Program:
#     puzstring = (
#         f"(r (c (q 0x{innerpuzhash}) ((c (q {binutils.disassemble(core)}) 1))))"
#     )
#     # return curry(DID_FULLPUZ_MOD, [innerpuzhash, core])
#     return Program(binutils.assemble(puzstring))


def create_fullpuz(innerpuz, genesis_id) -> Program:
    mod_hash = DID_CORE_MOD.get_tree_hash()
    return curry(DID_CORE_MOD, [mod_hash, genesis_id, innerpuz])


def fullpuz_hash_for_inner_puzzle_hash(
    mod_code, genesis_id, inner_puzzle_hash
) -> bytes32:
    """
    Given an inner puzzle hash, calculate a puzzle program hash for a specific cc.
    """
    gid_hash = genesis_id.get_tree_hash()
    return curry(
        mod_code, [mod_code.get_tree_hash(), gid_hash, inner_puzzle_hash]
    ).get_tree_hash(gid_hash, inner_puzzle_hash)


def get_pubkey_from_innerpuz(innerpuz: Program) -> G1Element:
    pubkey_program, id_list = uncurry_innerpuz(innerpuz)
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
    r = uncurry(puzzle)
    if r is None:
        return r
    inner_f, args = r
    if not is_did_innerpuz(inner_f):
        return None

    core_mod, pubkey, id_list = list(args.as_iter())
    return pubkey, id_list


def get_innerpuzzle_from_puzzle(puzzle: Program) -> Program:
    r = uncurry(puzzle)
    if r is None:
        return r
    inner_f, args = r
    if not is_did_core(inner_f):
        return None
    mod_hash, genesis_id, inner_puzzle = list(args.as_iter())
    return inner_puzzle


def get_genesis_from_puzzle(puzzle: Program):
    r = uncurry(puzzle)
    if r is None:
        return r
    inner_f, args = r
    if not is_did_core(inner_f):
        return None
    mod_hash, genesis_id, inner_puzzle = list(args.as_iter())
    return genesis_id.as_atom()


def get_recovery_message_puzzle(recovering_coin, newpuz):
    return curry(DID_RECOVERY_MESSAGE_MOD, [recovering_coin, newpuz])


def create_spend_for_message(parent_of_message, recovering_coin, newpuz):
    puzzle = get_recovery_message_puzzle(recovering_coin, newpuz)
    coin = Coin(parent_of_message, puzzle.get_tree_hash(), uint64(0))
    solution = Program.to([])
    coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
    return coinsol


# inspect puzzle and check it is a CC puzzle
def check_is_did_puzzle(puzzle: Program):
    r = uncurry(puzzle)
    if r is None:
        return r
    inner_f, args = r
    return is_did_core(inner_f)
