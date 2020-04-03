import time
from secrets import token_bytes

import clvm
from blspy import ExtendedPrivateKey
from clvm import run_program
from clvm_tools import binutils

from src.types.condition_opcodes import ConditionOpcode
from src.types.condition_var_pair import ConditionVarPair
from src.types.BLSSignature import BLSSignature
from src.types.program import Program
from src.util.condition_tools import parse_sexp_to_conditions
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk
from tests.wallet_tools import WalletTool


def float_to_str(f):
    float_string = repr(f)
    if "e" in float_string:  # detect scientific notation
        digits, exp_str = float_string.split("e")
        digits = digits.replace(".", "").replace("-", "")
        exp = int(exp_str)
        zero_padding = "0" * (
            abs(int(exp)) - 1
        )  # minus 1 for decimal point in the sci notation
        sign = "-" if f < 0 else ""
        if exp > 0:
            float_string = "{}{}{}.0".format(sign, digits, zero_padding)
        else:
            float_string = "{}0.{}{}".format(sign, zero_padding, digits)
    return float_string


def run_and_return_cost_time(chialisp):

    start = time.time()
    clvm_loop = f"((c (q ((c (f (a)) (c (f (a)) (c (f (r (a))) (c (f (r (r (a)))) (q ()))))))) (c (q ((c (i (f (r (a))) (q (i (q 1) ((c (f (a)) (c (f (a)) (c (- (f (r (a))) (q 1)) (c (f (r (r (a)))) (q ())))))) ((c (f (r (r (a)))) (q ()))))) (q (q ()))) (a)))) (a))))"
    loop_program = Program(binutils.assemble(clvm_loop))
    clvm_loop_solution = f"(1000 {chialisp})"
    solution_program = Program(binutils.assemble(clvm_loop_solution))

    cost, sexp = run_program(loop_program, solution_program)

    end = time.time()
    total_time = end - start

    return cost, total_time


def get_cost_compared_to_addition(addition_cost, addition_time, other_time):
    return (addition_cost * other_time) / addition_time


def benchmark_all_operators():
    addition = "(+ (q 1000000000) (q 1000000000))"
    substraction = "(- (q 1000000000) (q 1000000000))"
    multiply = "(* (q 1000000000) (q 1000000000))"
    greater = "(> (q 1000000000) (q 1000000000))"
    equal = "(= (q 1000000000) (q 1000000000))"
    if_clvm = "(i (= (q 1000000000) (q 1000000000)) (q 1000000000) (q 1000000000))"
    sha256tree = "(sha256 (q 1000000000))"
    pubkey_for_exp = "(pubkey_for_exp (q 1))"
    point_add = "(point_add (q 0x17f1d3a73197d7942695638c4fa9ac0fc3688c4f9774b905a14e3a3f171bac586c55e83ff97a1aeffb3af00adb22c6bb) (q 0x17f1d3a73197d7942695638c4fa9ac0fc3688c4f9774b905a14e3a3f171bac586c55e83ff97a1aeffb3af00adb22c6bb))"
    point_add_cost, point_add_time = run_and_return_cost_time(point_add)
    addition_cost, addition_time = run_and_return_cost_time(addition)
    substraction_cost, substraction_time = run_and_return_cost_time(substraction)
    multiply_cost, multiply_time = run_and_return_cost_time(multiply)
    greater_cost, greater_time = run_and_return_cost_time(greater)
    equal_cost, equal_time = run_and_return_cost_time(equal)
    if_cost, if_time = run_and_return_cost_time(if_clvm)
    sha256tree_cost, sha256tree_time = run_and_return_cost_time(sha256tree)
    pubkey_for_exp_cost, pubkey_for_exp_time = run_and_return_cost_time(pubkey_for_exp)

    one_addition = 1
    one_substraction = (
        get_cost_compared_to_addition(addition_cost, addition_time, substraction_time)
        / addition_cost
    )
    one_multiply = (
        get_cost_compared_to_addition(addition_cost, addition_time, multiply_time)
        / addition_cost
    )
    one_greater = (
        get_cost_compared_to_addition(addition_cost, addition_time, greater_time)
        / addition_cost
    )
    one_equal = (
        get_cost_compared_to_addition(addition_cost, addition_time, equal_time)
        / addition_cost
    )
    one_if = (
        get_cost_compared_to_addition(addition_cost, addition_time, if_time)
        / addition_cost
    )
    one_sha256 = (
        get_cost_compared_to_addition(addition_cost, addition_time, sha256tree_time)
        / addition_cost
    )
    one_pubkey_for_exp = (
        get_cost_compared_to_addition(addition_cost, addition_time, pubkey_for_exp_time)
        / addition_cost
    )
    one_point_add = (
        get_cost_compared_to_addition(addition_cost, addition_time, point_add_time)
        / addition_cost
    )

    print(f"cost of addition is: {one_addition}")
    print(f"cost of one_substraction is: {one_substraction}")
    print(f"cost of one_multiply is: {one_multiply}")
    print(f"cost of one_greater is: {one_greater}")
    print(f"cost of one_equal is: {one_equal}")
    print(f"cost of one_if is: {one_if}")
    print(f"cost of one_sha256 is: {one_sha256}")
    print(f"cost of one_pubkey_for_exp is: {one_pubkey_for_exp}")
    print(f"cost of one_point_add is: {one_point_add}")


if __name__ == "__main__":
    """
    Naive way to calculate cost ratio between vByte and CLVM cost unit.
    AggSig has assigned cost of 20vBytes, simple CLVM program is benchmarked against it.
    """
    wallet_tool = WalletTool()
    benchmark_all_operators()
    extended_secret_key: ExtendedPrivateKey = ExtendedPrivateKey.from_seed(b"a")
    puzzles = []
    solutions = []
    private_keys = []
    public_keys = []

    for i in range(0, 1000):
        private_key: BLSPrivateKey = BLSPrivateKey(
            extended_secret_key.private_child(i).get_private_key()
        )
        public_key = private_key.public_key()
        solution = wallet_tool.make_solution(
            {
                ConditionOpcode.ASSERT_MY_COIN_ID: [
                    ConditionVarPair(
                        ConditionOpcode.ASSERT_MY_COIN_ID, token_bytes(), None
                    )
                ]
            }
        )
        puzzle = puzzle_for_pk(public_key)
        puzzles.append(puzzle)
        solutions.append(solution)
        private_keys.append(private_key)
        public_keys.append(public_key)

    # Run Puzzle 1000 times
    puzzle_start = time.time()
    clvm_cost = 0
    for i in range(0, 1000):
        cost_run, sexp = run_program(puzzles[i], solutions[i])
        clvm_cost += cost_run

    puzzle_end = time.time()
    puzzle_time = puzzle_end - puzzle_start
    print(f"Puzzle_time is: {puzzle_time}")
    print(f"Puzzle cost sum is: {clvm_cost}")

    private_key = BLSPrivateKey(extended_secret_key.private_child(0).get_private_key())
    public_key = private_key.public_key()
    message = token_bytes()
    signature = private_key.sign(message)
    pk_message_pair = BLSSignature.PkMessagePair(public_key, message)

    # Run AggSig 1000 times
    agg_sig_start = time.time()
    agg_sig_cost = 0
    for i in range(0, 1000):
        valid = signature.validate([pk_message_pair])
        agg_sig_cost += 20
    agg_sig_end = time.time()
    agg_sig_time = agg_sig_end - agg_sig_start
    print(f"Aggsig Cost: {agg_sig_cost}")
    print(f"Aggsig time is: {agg_sig_time}")

    # clvm_should_cost = agg_sig_cost * puzzle_time / agg_sig_time
    clvm_should_cost = (agg_sig_cost * puzzle_time) / agg_sig_time
    print(f"Puzzle should cost: {clvm_should_cost}")
    constant = clvm_should_cost / clvm_cost
    format = float_to_str(constant)
    print(f"Constant factor: {format}")
    print(f"CLVM RATIO MULTIPLIER: {1/constant}")
