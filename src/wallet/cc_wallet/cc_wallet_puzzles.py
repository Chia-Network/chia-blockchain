from typing import Optional, Tuple

from clvm_tools import binutils
import clvm
import string
from src.types.BLSSignature import BLSSignature
from src.types.program import Program
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution


# This is for spending an existing coloured coin
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.util.ints import uint64


def cc_make_puzzle(innerpuzhash, core):
    # Puzzle runs the core, but stores innerpuzhash commitment
    puzstring = f"(r (c (q 0x{innerpuzhash}) ((c (q {core}) (a)))))"
    result = Program(binutils.assemble(puzstring))
    return result


# Makes a core given a genesisID (aka the "colour")
def cc_make_core(originID):
    # solution is f"({core} {parent_str} {my_amount} {innerpuzreveal} {innersol} {auditor_info} {aggees})"
    # parent_str is either an atom or list depending on the type of spend
    # auditor is (primary_input, innerpuzzlehash, amount)
    # aggees is left blank if you aren't the auditor otherwise it is a list of
    # (primary_input, innerpuzhash, coin_amount, output_amount) for every coin in the spend
    # Compiled from coloured_coins.clvm

    core = f"((c (q ((c (i (l (f (r (r (a))))) (q ((c (f (f (r (f (a))))) (c (f (a)) (c ((c (f (r (r (r (r (a)))))) (f (r (r (r (r (r (a))))))))) (c (q ()) (c (f (r (a))) (c (q ()) (c (sha256 (sha256 (f (f (r (r (a))))) ((c (f (r (f (f (a))))) (c (f (a)) (c (f (r (f (r (r (a)))))) (c (f (r (a))) (q ())))))) (f (r (r (f (r (r (a)))))))) ((c (f (r (f (f (a))))) (c (f (a)) (c ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (f (r (r (r (r (a)))))) (q ()))))) (c (f (r (a))) (q ())))))) (f (r (r (r (a)))))) (c (sha256 (f (f (r (r (r (r (r (r (a))))))))) ((c (f (r (f (f (a))))) (c (f (a)) (c (f (r (f (r (r (r (r (r (r (a)))))))))) (c (f (r (a))) (q ())))))) (f (r (r (f (r (r (r (r (r (r (a)))))))))))) (c (f (r (r (r (r (r (r (r (a))))))))) (q ())))))))))))) (q (c (c (q 51) (c (f (r (r (r (r (a)))))) (c (f (r (r (r (a))))) (q ())))) (c ((c (r (r (f (f (a))))) (c (f (a)) (c (f (r (r (a)))) (c (f (r (r (r (r (a)))))) (c (f (r (r (r (a))))) (q ()))))))) (q ()))))) (a)))) (c (q (((((c (i (l (f (r (a)))) (q ((c (f (f (f (f (a))))) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (f (r (r (r (a))))) (c ((c (r (f (f (f (a))))) (c (f (a)) (c (sha256 (f (f (f (r (a))))) ((c (f (r (f (f (a))))) (c (f (a)) (c (f (r (f (f (r (a)))))) (c (f (r (r (r (a))))) (q ())))))) (f (r (r (f (f (r (a)))))))) (c (f (r (r (a)))) (c (f (r (r (r (f (f (r (a)))))))) (c (f (r (r (r (r (a)))))) (q ())))))))) (c (+ (f (r (r (f (f (r (a))))))) (f (r (r (r (r (r (a)))))))) (c (+ (f (r (r (r (f (f (r (a)))))))) (f (r (r (r (r (r (r (a))))))))) (q ()))))))))))) (q ((c (i (= (f (r (r (r (r (r (a))))))) (f (r (r (r (r (r (r (a))))))))) (q (f (r (r (r (r (a))))))) (q (x))) (a))))) (a))) 5 (c (q 52) (c (sha256 (f (r (a))) ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (r (a)))) (q ()))) (c (c (q 5) (c (c (q 1) (c (f (r (r (r (a))))) (q ()))) (q ((q ()))))) (q ())))) (q ()))) (q ()))) (q ()))))) (q ())) (q ()))) (c (c (q 51) (c ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (a))) (q ()))) (q ((q ()))))) (q ()))) (q ()))))) (q (())))) (f (r (r (r (r (a)))))))) ((c (f (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (a))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (c (q 97) (c (f (r (r (a)))) (q ()))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ()))) (q ()))))) (c (i (= (f (r (a))) (q 0x{originID})) (q (c (q 53) (c (sha256 (f (r (a))) (f (r (r (a)))) (f (r (r (r (a)))))) (q ())))) (q (c (q 53) (c (sha256 (f (r (a))) (f (r (r (a)))) (q ())) (q ()))))) (a))) (((c (r (f (r (f (a))))) (c (f (a)) (c (f (r (r (r (a))))) (c (f (r (r (r (r (r (a))))))) (c (f (r (r (r (r (r (r (r (a))))))))) (c ((c (f (r (r (f (a))))) (c (f (a)) (c (f (r (a))) (c (f (r (r (a)))) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (c (f (r (r (r (r (r (a))))))) (c (f (r (r (r (r (r (r (a)))))))) (q ())))))))))) (q ())))))))) (c (i (f (r (r (r (a))))) (q ((c (f (f (f (f (a))))) (c (f (a)) (c (f (r (r (r (a))))) (c (f (r (r (a)))) (c (f (r (a))) (c (f (r (r (r (r (a)))))) (q (() ())))))))))) (q (f (r (r (r (r (a)))))))) (a))) ((c (i (f (r (a))) (q ((c (i (= (f (f (f (r (a))))) (q 51)) (q ((c (f (r (r (f (a))))) (c (f (a)) (c (r (f (r (a)))) (c (c (c (q 51) (c ((c (f (r (f (f (a))))) (c (f (a)) (c (f (r (f (f (r (a)))))) (c (f (r (r (r (a))))) (q ())))))) (c (f (r (r (f (f (r (a))))))) (q ())))) (f (r (r (a))))) (c (f (r (r (r (a))))) (c (+ (f (r (r (f (f (r (a))))))) (f (r (r (r (r (a))))))) (c (f (r (r (r (r (r (a))))))) (c (f (r (r (r (r (r (r (a)))))))) (q ()))))))))))) (q ((c (f (r (r (f (a))))) (c (f (a)) (c (r (f (r (a)))) (c (c (f (f (r (a)))) (f (r (r (a))))) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (c (f (r (r (r (r (r (a))))))) (c (f (r (r (r (r (r (r (a)))))))) (q ())))))))))))) (a)))) (q (c (c (q 53) (c (f (r (r (r (r (r (a))))))) (q ()))) (c (c (q 52) (c (sha256 (f (r (r (r (r (r (r (a)))))))) ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (r (r (r (r (a))))))) (q ()))) (q ((q ()))))) (q ()))) (q ()))))) (q ())) (q ()))) (c (c (q 51) (c ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (r (r (r (r (r (a)))))))) (q ()))) (c (c (q 5) (c (c (q 1) (c (f (r (r (r (r (a)))))) (q ()))) (q ((q ()))))) (q ())))) (q ()))) (q ()))) (q ()))))) (q (())))) (f (r (r (a))))))))) (a))) ((c (i (l (f (r (a)))) (q ((c (i ((c (i ((c (i (l (f (f (r (a))))) (q (q ())) (q (q 1))) (a))) (q ((c (i (= (f (f (r (a)))) (q 97)) (q (q 1)) (q (q ()))) (a)))) (q (q ()))) (a))) (q (f (r (f (r (a)))))) (q (sha256 (q 2) ((c (f (r (r (r (f (a)))))) (c (f (a)) (c (f (f (r (a)))) (q ()))))) ((c (f (r (r (r (f (a)))))) (c (f (a)) (c (r (f (r (a)))) (q ())))))))) (a)))) (q (sha256 (q 1) (f (r (a)))))) (a))) (c (i (l (f (r (a)))) (q (sha256 (q 2) ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (f (f (r (a)))) (q ()))))) ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (sha256 (q 1) (f (r (a)))))) (a)))) (a))))"  # type: ignore # noqa

    return core


def cc_make_eve_solution(parent_id: bytes32, full_puzzlehash: bytes32, amount: uint64):
    sol = f"(() 0x{parent_id} {amount} 0x{full_puzzlehash} () () ())"
    return Program(binutils.assemble(sol))


# This is for spending a recieved coloured coin
def cc_make_solution(
    core: str,
    parent_info: Tuple[bytes32, bytes32, uint64],
    amount: uint64,
    innerpuzreveal: str,
    innersol: str,
    auditor: Optional[Tuple[bytes32, bytes32, uint64]],
    auditees=None,
    genesis=False,
):
    parent_str = ""
    # parent_info is a triplet if parent was coloured or an atom if parent was genesis coin or we're a printed 0 val
    # genesis coin isn't coloured, child of genesis uses originID, all subsequent children use triplets
    # auditor is (primary_input, innerpuzzlehash, amount)
    # aggees should be (primary_input, innerpuzhash, coin_amount, output_amount)
    if not genesis:
        #  (parent primary input, parent inner puzzle hash, parent amount)
        if parent_info[1][0:2] == "0x":
            parent_str = f"(0x{parent_info[0]} {parent_info[1]} {parent_info[2]})"
        else:
            parent_str = f"(0x{parent_info[0]} 0x{parent_info[1]} {parent_info[2]})"
    else:
        parent_str = f"0x{parent_info[0].hex()}"

    auditor_formatted = "()"
    if auditor is not None:
        auditor_formatted = f"(0x{auditor[0]} 0x{auditor[1]} {auditor[2]})"

    aggees = "("
    if auditees is not None:
        for auditee in auditees:
            aggees = (
                aggees + f"(0x{auditee[0]} 0x{auditee[1]} {auditee[2]} {auditee[3]})"
            )

    aggees = aggees + ")"

    sol = f"(0x{Program(binutils.assemble(core)).get_tree_hash()} {parent_str} {amount} {innerpuzreveal} {innersol} {auditor_formatted} {aggees})"  # type: ignore # noqa
    return Program(binutils.assemble(sol))


def get_genesis_from_puzzle(puzzle: str):
    return puzzle[-2687:].split(")")[0]


def get_genesis_from_core(core: str):
    return core[-2678:].split(")")[0]


def get_innerpuzzle_from_puzzle(puzzle: str):
    return puzzle[9:75]


# Make sure that a generated E lock is spent in the spendbundle
def create_spend_for_ephemeral(parent_of_e, auditor_coin, spend_amount):
    puzstring = f"(r (r (c (q 0x{auditor_coin.name()}) (c (q {spend_amount}) (q ())))))"
    puzzle = Program(binutils.assemble(puzstring))
    coin = Coin(parent_of_e.name(), puzzle.get_tree_hash(), uint64(0))
    solution = Program(binutils.assemble("()"))
    coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
    return coinsol


# Make sure that a generated A lock is spent in the spendbundle
def create_spend_for_auditor(parent_of_a, auditee):
    puzstring = f"(r (c (q 0x{auditee.name()}) (q ())))"
    puzzle = Program(binutils.assemble(puzstring))
    coin = Coin(parent_of_a.name(), puzzle.get_tree_hash(), uint64(0))
    solution = Program(binutils.assemble("()"))
    coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
    return coinsol


def cc_generate_eve_spend(coin: Coin, full_puzzle: Program):
    solution = cc_make_eve_solution(
        coin.parent_coin_info, coin.puzzle_hash, coin.amount
    )
    list_of_solutions = [CoinSolution(coin, clvm.to_sexp_f([full_puzzle, solution]),)]
    aggsig = BLSSignature.aggregate([])
    spend_bundle = SpendBundle(list_of_solutions, aggsig)
    return spend_bundle


# Returns the relative difference in value between the amount outputted by a puzzle and solution and a coin's amount
def get_output_discrepancy_for_puzzle_and_solution(coin, puzzle, solution):
    discrepancy = coin.amount - get_output_amount_for_puzzle_and_solution(
        puzzle, solution
    )
    return discrepancy

    # Returns the amount of value outputted by a puzzle and solution


def get_output_amount_for_puzzle_and_solution(puzzle, solution):
    conditions = clvm.run_program(puzzle, solution)[1]
    amount = 0
    while conditions != b"":
        opcode = conditions.first().first()
        if opcode == b"3":  # Check if CREATE_COIN
            amount_str = binutils.disassemble(conditions.first().rest().rest().first())
            if amount_str == "()":
                conditions = conditions.rest()
                continue
            elif amount_str[0:2] == "0x":  # Check for wonky decompilation
                amount += int(amount_str, 16)
            else:
                amount += int(amount_str, 10)
        conditions = conditions.rest()
    return amount


# inspect puzzle and check it is a CC puzzle
def check_is_cc_puzzle(puzzle: Program):
    puzzle_string = binutils.disassemble(puzzle)
    if len(puzzle_string) < 4000:
        return False
    inner_puzzle = puzzle_string[11:75]
    if all(c in string.hexdigits for c in inner_puzzle) is not True:
        return False
    genesisCoin = get_genesis_from_puzzle(puzzle_string)
    if all(c in string.hexdigits for c in genesisCoin) is not True:
        return False
    if cc_make_puzzle(inner_puzzle, cc_make_core(genesisCoin)) == puzzle:
        return True
    else:
        return False
