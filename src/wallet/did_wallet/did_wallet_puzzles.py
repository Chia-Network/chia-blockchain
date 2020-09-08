from clvm_tools import binutils
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
DID_GROUP_MOD = load_clvm("did_groups.clvm")

# NULL_F = Program.from_bytes(bytes.fromhex("ff01ff8080"))  # (q ())


def curry(*args, **kwargs):
    """
    The clvm_tools version of curry returns `cost, program` for now.
    Eventually it will just return `program`. This placeholder awaits that day.
    """
    cost, prog = ct_curry(*args, **kwargs)
    return Program.to(prog)


def create_core(genesis_coin_id: bytes) -> str:
    core = f"((c (q ((c 20 (c 2 (c 5 (c 11 (c 23 (c ((c 30 (c 2 (c 47 (q ()))))) (c ((c 47 95)) (q ())))))))))) (c (q (((53 5 16 (c (sha256 (q 0x{genesis_coin_id.hex()}) ((c 26 (c 2 (c 5 (c 23 (q ())))))) 11) (q ()))) ((c (i ((c 18 (c 2 (c 95 (q (())))))) (q (c ((c 28 (c 2 (c 11 (c 47 (c 23 (c 5 (q ())))))))) 95)) (q (x))) 1)) (c (i (> 23 (q ())) (q ((c (i (l 5) (q (c (q 53) (c (sha256 (sha256 9 ((c 26 (c 2 (c 21 (c 47 (q ())))))) 45) ((c 26 (c 2 (c 11 (c 47 (q ())))))) 23) (q ())))) (q ((c 24 (c 2 (c 11 (c 23 (c 47 (q ()))))))))) 1))) (q (x))) 1)) (((c (i 5 (q ((c (i (= 17 (q 51)) (q ((c (i (> 89 (q ())) (q ((c (i 11 (q (x)) (q ((c 18 (c 2 (c 13 (q (q)))))))) 1))) (q ((c 18 (c 2 (c 13 (c 11 (q ())))))))) 1))) (q ((c 18 (c 2 (c 13 (c 11 (q ())))))))) 1))) (q (q 1))) 1)) (c 22 (c 2 (c (c (q 7) (c (c (q 5) (c (c (q 1) (c 5 (q ()))) (c (c (c (q 5) (c (c (q 1) (c (c (q 97) (c 11 (q ()))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ()))) (q ()))))) ((c (i (l 5) (q ((c (i ((c (i ((c (i (l 9) (q (q ())) (q (q 1))) 1)) (q ((c (i (= 9 (q 97)) (q (q 1)) (q (q ()))) 1))) (q (q ()))) 1)) (q 21) (q (sha256 (q 2) ((c 22 (c 2 (c 9 (q ()))))) ((c 22 (c 2 (c 13 (q ())))))))) 1))) (q (sha256 (q 1) 5))) 1)) (c (i (l 5) (q (sha256 (q 2) ((c 30 (c 2 (c 9 (q ()))))) ((c 30 (c 2 (c 13 (q ()))))))) (q (sha256 (q 1) 5))) 1))) 1)))"  # type: ignore # noqa
    return core


def create_innerpuz(pubkey: bytes, identities: List[bytes]) -> Program:
    id_list = []
    for id in identities:
        id_list.append(format_DID_to_corehash(id))
    return curry(DID_INNERPUZ_MOD, [pubkey, id_list])


def create_fullpuz(innerpuzhash, core) -> str:
    puzstring = f"(r (c (q 0x{innerpuzhash}) ((c (q {core}) (a)))))"
    return puzstring


def get_pubkey_from_innerpuz(innerpuz: Program) -> G1Element:
    pubkey_program, id_list = uncurry_innerpuz(innerpuz)
    pubkey = G1Element.from_bytes(pubkey_program.as_atom())
    return pubkey


def is_did_innerpuz(inner_f: Program):
    """
    You may want to generalize this if different `CC_MOD` templates are supported.
    """
    return inner_f == DID_INNERPUZ_MOD


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

    pubkey, id_list = list(args.as_iter())
    return pubkey, id_list


def get_innerpuzzle_from_puzzle(puzzle: str):
    return puzzle[9:75]


# the genesis is also the ID
def get_genesis_from_puzzle(puzzle: str) -> str:
    return puzzle[132:196]


def format_DID_to_corehash(did: bytes):
    core_str = create_core(did)
    return Program(binutils.assemble(core_str)).get_tree_hash()


def create_spend_for_mesasage(parent_of_message, recovering_coin, newpuz):
    puzstring = f"(r (r (c (q 0x{recovering_coin}) (c (q 0x{newpuz}) (q ())))))"
    puzzle = Program(binutils.assemble(puzstring))
    coin = Coin(parent_of_message, puzzle.get_tree_hash(), uint64(0))
    solution = Program(binutils.assemble("()"))
    coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
    return coinsol


# inspect puzzle and check it is a CC puzzle
def check_is_did_puzzle(puzzle: Program):
    puzzle_string = binutils.disassemble(puzzle)
    if len(puzzle_string) < 1400 or len(puzzle_string) > 1500:
        return False
    inner_puzzle = puzzle_string[11:75]
    if all(c in string.hexdigits for c in inner_puzzle) is not True:
        return False
    genesisCoin = get_genesis_from_puzzle(puzzle_string)
    if all(c in string.hexdigits for c in genesisCoin) is not True:
        return False
    if create_fullpuz(inner_puzzle, create_core(bytes.fromhex(genesisCoin))) == puzzle:
        return True
    else:
        return False
