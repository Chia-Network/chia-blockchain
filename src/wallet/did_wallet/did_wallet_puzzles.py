from clvm_tools import binutils
from src.types.program import Program
from typing import List
from blspy import PublicKey
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.util.ints import uint64
import string
import clvm


def create_core(genesis_coin_id: bytes) -> str:
    core = f"((c (q ((c 20 (c 2 (c 5 (c 11 (c 23 (c ((c 30 (c 2 (c 47 (q ()))))) (c ((c 47 95)) (q ())))))))))) (c (q (((53 5 16 (c (sha256 (q 0x{genesis_coin_id.hex()}) ((c 26 (c 2 (c 5 (c 23 (q ())))))) 11) (q ()))) ((c (i ((c 18 (c 2 (c 95 (q (())))))) (q (c ((c 28 (c 2 (c 11 (c 47 (c 23 (c 5 (q ())))))))) 95)) (q (x))) 1)) (c (i (> 23 (q ())) (q ((c (i (l 5) (q (c (q 53) (c (sha256 (sha256 9 ((c 26 (c 2 (c 21 (c 47 (q ())))))) 45) ((c 26 (c 2 (c 11 (c 47 (q ())))))) 23) (q ())))) (q ((c 24 (c 2 (c 11 (c 23 (c 47 (q ()))))))))) 1))) (q (x))) 1)) (((c (i 5 (q ((c (i (= 17 (q 51)) (q ((c (i (> 89 (q ())) (q ((c (i 11 (q (x)) (q ((c 18 (c 2 (c 13 (q (q)))))))) 1))) (q ((c 18 (c 2 (c 13 (c 11 (q ())))))))) 1))) (q ((c 18 (c 2 (c 13 (c 11 (q ())))))))) 1))) (q (q 1))) 1)) (c 22 (c 2 (c (c (q 7) (c (c (q 5) (c (c (q 1) (c 5 (q ()))) (c (c (c (q 5) (c (c (q 1) (c (c (q 97) (c 11 (q ()))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ()))) (q ()))))) ((c (i (l 5) (q ((c (i ((c (i ((c (i (l 9) (q (q ())) (q (q 1))) 1)) (q ((c (i (= 9 (q 97)) (q (q 1)) (q (q ()))) 1))) (q (q ()))) 1)) (q 21) (q (sha256 (q 2) ((c 22 (c 2 (c 9 (q ()))))) ((c 22 (c 2 (c 13 (q ())))))))) 1))) (q (sha256 (q 1) 5))) 1)) (c (i (l 5) (q (sha256 (q 2) ((c 30 (c 2 (c 9 (q ()))))) ((c 30 (c 2 (c 13 (q ()))))))) (q (sha256 (q 1) 5))) 1))) 1)))"  # type: ignore # noqa
    return core


def create_innerpuz(pubkey: bytes, identities: List[bytes]) -> str:
    id_list = "("
    for id in identities:
        id_list = id_list + "0x" + id.hex() + " "
    id_list = id_list + ")"

    innerpuz = f"((c (q ((c (i 5 (q ((c (i (= 5 (q 1)) (q (c (c 56 (c 95 (c 11 (q ())))) (c (c 56 (c ((c 62 (c 2 (c ((c 22 (c 2 (c 47 (c 23 (q ())))))) (q ()))))) (q (())))) (c ((c 44 (c 2 (c 23 (q ()))))) (c (c 40 (c 47 (q ()))) (q ())))))) (q ((c 20 (c 2 (c 46 (c 47 (c (c (c 56 (c 23 (c 11 (q ())))) (q ())) (c 23 (c 191 (q ()))))))))))) 1))) (q (c (c 56 (c 23 (c 11 (q ())))) (c ((c 44 (c 2 (c 23 (q ()))))) (q ()))))) 1))) (c (q (((57 52 . 51) ((c (i 5 (q ((c 20 (c 2 (c 13 (c 11 (c (c ((c 18 (c 2 (c ((c 60 (c 2 (c 9 (c 287 (c 671 (c 1439 (q ())))))))) (c 11 (c 47 (q ()))))))) 23) (c 47 (c 223 (q ())))))))))) (q 23)) 1)) (c 16 (c (q 0x{pubkey.hex()}) (c 5 (q ())))) 11 11 ((c 62 (c 2 (c ((c 58 (c 2 (c 23 (c ((c 42 (c 2 (c 5 (q ()))))) (q ())))))) (q ()))))) 47) ((c 40 (c (sha256 5 ((c 62 (c 2 (c ((c 22 (c 2 (c 11 (c 23 (q ())))))) (q ()))))) (q ())) (q ()))) (c (c (q 5) (c (q (q ((c 20 (c 2 (c 5 (c 11 (c 23 (c ((c 30 (c 2 (c 47 (q ()))))) (c ((c 47 95)) (q ()))))))))))) (c (c (q 5) (c (c (q 1) (c (c (c (c (q 53) (c (q 5) (c (q 16) (c (c (q 5) (c (c (q 11) (c (c (q 1) (c 5 (q ()))) (q (((c 26 (c 2 (c 5 (c 23 (q ())))))) 11)))) (q ((q ()))))) (q ()))))) (q (((c (i ((c 18 (c 2 (c 95 (q (())))))) (q (c ((c 28 (c 2 (c 11 (c 47 (c 23 (c 5 (q ())))))))) 95)) (q (x))) 1)) (c (i (> 23 (q ())) (q ((c (i (l 5) (q (c (q 53) (c (sha256 (sha256 9 ((c 26 (c 2 (c 21 (c 47 (q ())))))) 45) ((c 26 (c 2 (c 11 (c 47 (q ())))))) 23) (q ())))) (q ((c 24 (c 2 (c 11 (c 23 (c 47 (q ()))))))))) 1))) (q (x))) 1)))) (q ((((c (i 5 (q ((c (i (= 17 (q 51)) (q ((c (i (> 89 (q ())) (q ((c (i 11 (q (x)) (q ((c 18 (c 2 (c 13 (q (q)))))))) 1))) (q ((c 18 (c 2 (c 13 (c 11 (q ())))))))) 1))) (q ((c 18 (c 2 (c 13 (c 11 (q ())))))))) 1))) (q (q 1))) 1)) (c 22 (c 2 (c (c (q 7) (c (c (q 5) (c (c (q 1) (c 5 (q ()))) (c (c (c (q 5) (c (c (q 1) (c (c (q 97) (c 11 (q ()))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ()))) (q ()))))) ((c (i (l 5) (q ((c (i ((c (i ((c (i (l 9) (q (q ())) (q (q 1))) 1)) (q ((c (i (= 9 (q 97)) (q (q 1)) (q (q ()))) 1))) (q (q ()))) 1)) (q 21) (q (sha256 (q 2) ((c 22 (c 2 (c 9 (q ()))))) ((c 22 (c 2 (c 13 (q ())))))))) 1))) (q (sha256 (q 1) 5))) 1)) (c (i (l 5) (q (sha256 (q 2) ((c 30 (c 2 (c 9 (q ()))))) ((c 30 (c 2 (c 13 (q ()))))))) (q (sha256 (q 1) 5))) 1)))) (q ()))) (q (q)))) (q ())))) (q ())) 5 (q 7) (c (c (q 5) (c (c (q 1) (c 5 (q ()))) (c (c (c (q 5) (c (c (q 1) (c 11 (q ()))) (q ((a))))) (q ())) (q ())))) (q ()))) (c (q 7) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c 5 (q ()))) (c (c (q 5) (c (c (q 1) (c 11 (q ()))) (q ((q ()))))) (q ())))) (q ()))) (q ()))) {id_list} (c (i (l 5) (q (sha256 (q 2) ((c 62 (c 2 (c 9 (q ()))))) ((c 62 (c 2 (c 13 (q ()))))))) (q (sha256 (q 1) 5))) 1))) 1)))"  # type: ignore # noqa
    # breakpoint()
    return innerpuz


def create_fullpuz(innerpuzhash, core) -> str:
    puzstring = f"(r (c (q 0x{innerpuzhash}) ((c (q {core}) (a)))))"
    # breakpoint()
    return puzstring


def get_pubkey_from_innerpuz(innerpuz: str):
    pubkey = PublicKey.from_bytes(bytes.fromhex(innerpuz[626:722]))
    return pubkey


def get_innerpuzzle_from_puzzle(puzzle: str):
    return puzzle[9:75]


# the genesis is also the ID
def get_genesis_from_puzzle(puzzle: str) -> str:
    return puzzle[132:196]


def create_spend_for_mesasage(parent_of_message, recovering_coin, newpuz):
    puzstring = f"(r (r (c (q 0x{recovering_coin}) (c (q 0x{newpuz}) (q ())))))"
    puzzle = Program(binutils.assemble(puzstring))
    coin = Coin(parent_of_message, puzzle.get_tree_hash(), uint64(0))
    # breakpoint()
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
