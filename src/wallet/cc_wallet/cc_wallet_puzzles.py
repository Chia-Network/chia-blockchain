from clvm_tools import binutils
import clvm
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.sized_bytes import bytes32


# This is for spending an existing coloured coin
def cc_make_puzzle(self, innerpuzhash, core):
    key = f"{innerpuzhash}{core}"
    # Check if we have made this puzzle before for speedup
    if key in self.puzzle_cache:
        return self.puzzle_cache[key]
    # Puzzle runs the core, but stores innerpuzhash commitment
    puzstring = f"(r (c (q 0x{innerpuzhash}) ((c (q {core}) (a)))))"
    result = Program(binutils.assemble(puzstring))
    self.puzzle_cache[key] = result
    return result


# Makes a core given a genesisID (aka the "colour")
def cc_make_core(self, originID):
    # solution is f"({core} {parent_str} {my_amount} {innerpuzreveal} {innersol} {auditor_info} {aggees})"
    # parent_str is either an atom or list depending on the type of spend
    # auditor is (primary_input, innerpuzzlehash, amount)
    # aggees is left blank if you aren't the auditor otherwise it is a list of (primary_input, innerpuzhash, coin_amount, output_amount) for every coin in the spend
    # Compiled from coloured_coins.clvm

    core = f"((c (q ((c (i (l (f (r (r (a))))) (q ((c (f (f (r (f (a))))) (c (f (a)) (c ((c (f (r (r (r (r (a)))))) (f (r (r (r (r (r (a))))))))) (c (q ()) (c (f (r (a))) (c (q ()) (c (sha256 (sha256 (f (f (r (r (a))))) ((c (f (r (f (f (a))))) (c (f (a)) (c (f (r (f (r (r (a)))))) (c (f (r (a))) (q ())))))) (f (r (r (f (r (r (a)))))))) ((c (f (r (f (f (a))))) (c (f (a)) (c ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (f (r (r (r (r (a)))))) (q ()))))) (c (f (r (a))) (q ())))))) (f (r (r (r (a)))))) (c (sha256 (f (f (r (r (r (r (r (r (a))))))))) ((c (f (r (f (f (a))))) (c (f (a)) (c (f (r (f (r (r (r (r (r (r (a)))))))))) (c (f (r (a))) (q ())))))) (f (r (r (f (r (r (r (r (r (r (a)))))))))))) (c (f (r (r (r (r (r (r (r (a))))))))) (q ())))))))))))) (q (c (c (q 51) (c ((c (f (r (f (f (a))))) (c (f (a)) (c ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (f (r (r (r (r (a)))))) (q ()))))) (c (f (r (a))) (q ())))))) (c (f (r (r (r (a))))) (q ())))) (c ((c (r (r (f (f (a))))) (c (f (a)) (c (f (r (r (a)))) (c ((c (f (r (f (f (a))))) (c (f (a)) (c ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (f (r (r (r (r (a)))))) (q ()))))) (c (f (r (a))) (q ())))))) (c (f (r (r (r (a))))) (q ()))))))) (q ()))))) (a)))) (c (q (((((c (i (l (f (r (a)))) (q ((c (f (f (f (f (a))))) (c (f (a)) (c (r (f (r (a)))) (c (f (r (r (a)))) (c (f (r (r (r (a))))) (c ((c (r (f (f (f (a))))) (c (f (a)) (c (sha256 (f (f (f (r (a))))) ((c (f (r (f (f (a))))) (c (f (a)) (c (f (r (f (f (r (a)))))) (c (f (r (r (r (a))))) (q ())))))) (f (r (r (f (f (r (a)))))))) (c (f (r (r (a)))) (c (f (r (r (r (f (f (r (a)))))))) (c (f (r (r (r (r (a)))))) (q ())))))))) (c (+ (f (r (r (f (f (r (a))))))) (f (r (r (r (r (r (a)))))))) (c (+ (f (r (r (r (f (f (r (a)))))))) (f (r (r (r (r (r (r (a))))))))) (q ()))))))))))) (q ((c (i (= (f (r (r (r (r (r (a))))))) (f (r (r (r (r (r (r (a))))))))) (q (f (r (r (r (r (a))))))) (q (x))) (a))))) (a))) 5 (c (q 52) (c (sha256 (f (r (a))) ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (r (a)))) (q ()))) (c (c (q 5) (c (c (q 1) (c (f (r (r (r (a))))) (q ()))) (q ((q ()))))) (q ())))) (q ()))) (q ()))) (q ()))))) (q ())) (q ()))) (c (c (q 51) (c ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (a))) (q ()))) (q ((q ()))))) (q ()))) (q ()))))) (q (())))) (f (r (r (r (r (a)))))))) ((c (f (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (a))) (q ()))) (c (c (c (q 5) (c (c (q 1) (c (c (q 97) (c (f (r (r (a)))) (q ()))) (q ()))) (q ((a))))) (q ())) (q ())))) (q ()))) (q ()))))) (c (i (= (f (r (a))) (q 0x{originID})) (q (c (q 53) (c (sha256 (f (r (a))) (f (r (r (a)))) (f (r (r (r (a)))))) (q ())))) (q (c (q 53) (c (sha256 (f (r (a))) (f (r (r (a)))) (q ())) (q ()))))) (a))) (((c (r (f (r (f (a))))) (c (f (a)) (c (f (r (r (r (a))))) (c (f (r (r (r (r (r (a))))))) (c (f (r (r (r (r (r (r (r (a))))))))) (c ((c (f (r (r (f (a))))) (c (f (a)) (c (f (r (a))) (c (f (r (r (a)))) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (c (f (r (r (r (r (r (a))))))) (c (f (r (r (r (r (r (r (a)))))))) (q ())))))))))) (q ())))))))) (c (i (f (r (r (r (a))))) (q ((c (f (f (f (f (a))))) (c (f (a)) (c (f (r (r (r (a))))) (c (f (r (r (a)))) (c (f (r (a))) (c (f (r (r (r (r (a)))))) (q (() ())))))))))) (q (f (r (r (r (r (a)))))))) (a))) ((c (i (f (r (a))) (q ((c (i (= (f (f (f (r (a))))) (q 51)) (q ((c (f (r (r (f (a))))) (c (f (a)) (c (r (f (r (a)))) (c (c (c (q 51) (c ((c (f (r (f (f (a))))) (c (f (a)) (c (f (r (f (f (r (a)))))) (c (f (r (r (r (a))))) (q ())))))) (c (f (r (r (f (f (r (a))))))) (q ())))) (f (r (r (a))))) (c (f (r (r (r (a))))) (c (+ (f (r (r (f (f (r (a))))))) (f (r (r (r (r (a))))))) (c (f (r (r (r (r (r (a))))))) (c (f (r (r (r (r (r (r (a)))))))) (q ()))))))))))) (q ((c (f (r (r (f (a))))) (c (f (a)) (c (r (f (r (a)))) (c (c (f (f (r (a)))) (f (r (r (a))))) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (c (f (r (r (r (r (r (a))))))) (c (f (r (r (r (r (r (r (a)))))))) (q ())))))))))))) (a)))) (q (c (c (q 53) (c (f (r (r (r (r (r (a))))))) (q ()))) (c (c (q 52) (c (sha256 (f (r (r (r (r (r (r (a)))))))) ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (r (r (r (r (a))))))) (q ()))) (q ((q ()))))) (q ()))) (q ()))))) (q ())) (q ()))) (c (c (q 51) (c ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (c (q 7) (c (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (r (r (r (r (r (r (a)))))))) (q ()))) (c (c (q 5) (c (c (q 1) (c (f (r (r (r (r (a)))))) (q ()))) (q ((q ()))))) (q ())))) (q ()))) (q ()))) (q ()))))) (q (())))) (f (r (r (a))))))))) (a))) ((c (i (l (f (r (a)))) (q ((c (i ((c (i ((c (i (l (f (f (r (a))))) (q (q ())) (q (q 1))) (a))) (q ((c (i (= (f (f (r (a)))) (q 97)) (q (q 1)) (q (q ()))) (a)))) (q (q ()))) (a))) (q (f (r (f (r (a)))))) (q (sha256 (q 2) ((c (f (r (r (r (f (a)))))) (c (f (a)) (c (f (f (r (a)))) (q ()))))) ((c (f (r (r (r (f (a)))))) (c (f (a)) (c (r (f (r (a)))) (q ())))))))) (a)))) (q (sha256 (q 1) (f (r (a)))))) (a))) (c (i (l (f (r (a)))) (q (sha256 (q 2) ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (f (f (r (a)))) (q ()))))) ((c (r (r (r (r (f (a)))))) (c (f (a)) (c (r (f (r (a)))) (q ()))))))) (q (sha256 (q 1) (f (r (a)))))) (a)))) (a))))"

    return core

# Make sure that a generated E lock is spent in the spendbundle
    def create_spend_for_ephemeral(self, parent_of_e, auditor_coin, spend_amount):
        puzstring = f"(r (r (c (q 0x{auditor_coin.name()}) (c (q {spend_amount}) (q ())))))"
        puzzle = Program(binutils.assemble(puzstring))
        coin = Coin(parent_of_e, ProgramHash(puzzle), 0)
        solution = Program(binutils.assemble("()"))
        coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
        return coinsol

    # Make sure that a generated A lock is spent in the spendbundle
    def create_spend_for_auditor(self, parent_of_a, auditee):
        puzstring = f"(r (c (q 0x{auditee.name()}) (q ())))"
        puzzle = Program(binutils.assemble(puzstring))
        coin = Coin(parent_of_a, ProgramHash(puzzle), 0)
        solution = Program(binutils.assemble("()"))
        coinsol = CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
        return coinsol
