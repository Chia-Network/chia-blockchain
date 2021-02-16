import math
from binascii import hexlify

from clvm_tools import binutils

from src.types.condition_opcodes import ConditionOpcode
from src.types.blockchain_format.program import Program
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint64
from src.wallet.chialisp import sexp
from src.wallet.puzzles.load_clvm import load_clvm

RATE_LIMITED_MODE = 1
AGGREGATION_MODE = 2
CLAWBACK_MODE = 3


def rl_puzzle_for_pk(
    pubkey: bytes,
    rate_amount: uint64,
    interval_time: uint64,
    origin_id: bytes32,
    clawback_pk: bytes,
):
    """
    Solution to this puzzle must be in format:
    (1 my_parent_id, my_puzzlehash, my_amount, outgoing_puzzle_hash, outgoing_amount,
     min_block_time, parent_parent_id, parent_amount, fee)
    RATE LIMIT LOGIC:
    M - chia_per_interval
    N - interval_blocks
    V - amount being spent
    MIN_BLOCK_AGE = V / (M / N)
    if not (min_block_age * M >=  V * N) do X (raise)
    ASSERT_COIN_BLOCK_AGE_EXCEEDS min_block_age
    """

    MOD = load_clvm("../puzzles/rl.clvm")
    return MOD.curry(pubkey, rate_amount, interval_time, origin_id, clawback_pk)


def rl_make_aggregation_solution(myid, wallet_coin_primary_input, wallet_coin_amount):
    opcode_myid = "0x" + hexlify(myid).decode("ascii")
    primary_input = "0x" + hexlify(wallet_coin_primary_input).decode("ascii")
    sol = sexp(opcode_myid, primary_input, wallet_coin_amount)
    return Program.to(binutils.assemble(sol))


def make_clawback_solution(puzzlehash, amount, fee):
    opcode_create = hexlify(ConditionOpcode.CREATE_COIN).decode("ascii")
    solution = sexp(CLAWBACK_MODE, sexp("0x" + opcode_create, "0x" + str(puzzlehash), amount - fee))
    return Program.to(binutils.assemble(solution))


def rl_make_solution_mode_2(
    my_puzzle_hash,
    consolidating_primary_input,
    consolidating_coin_puzzle_hash,
    outgoing_amount,
    my_primary_input,
    incoming_amount,
    parent_amount,
    my_parent_parent_id,
):
    my_puzzle_hash = hexlify(my_puzzle_hash).decode("ascii")
    consolidating_primary_input = hexlify(consolidating_primary_input).decode("ascii")
    consolidating_coin_puzzle_hash = hexlify(consolidating_coin_puzzle_hash).decode("ascii")
    primary_input = hexlify(my_primary_input).decode("ascii")
    sol = sexp(
        AGGREGATION_MODE,
        "0x" + my_puzzle_hash,
        "0x" + consolidating_primary_input,
        "0x" + consolidating_coin_puzzle_hash,
        outgoing_amount,
        "0x" + primary_input,
        incoming_amount,
        parent_amount,
        "0x" + str(my_parent_parent_id),
    )
    return Program.to(binutils.assemble(sol))


def solution_for_rl(
    my_parent_id: bytes32,
    my_puzzlehash: bytes32,
    my_amount: uint64,
    out_puzzlehash: bytes32,
    out_amount: uint64,
    my_parent_parent_id: bytes32,
    parent_amount: uint64,
    interval,
    limit,
    fee,
):
    """
    Solution is (1 my_parent_id, my_puzzlehash, my_amount, outgoing_puzzle_hash, outgoing_amount,
    min_block_time, parent_parent_id, parent_amount, fee)
    min block time = Math.ceil((new_amount * self.interval) / self.limit)
    """

    min_block_count = math.ceil((out_amount * interval) / limit)
    solution = sexp(
        RATE_LIMITED_MODE,
        "0x" + my_parent_id.hex(),
        "0x" + my_puzzlehash.hex(),
        my_amount,
        "0x" + out_puzzlehash.hex(),
        out_amount,
        min_block_count,
        "0x" + my_parent_parent_id.hex(),
        parent_amount,
        fee,
    )
    return Program.to(binutils.assemble(solution))


def rl_make_aggregation_puzzle(wallet_puzzle):
    """
    If Wallet A wants to send further funds to Wallet B then they can lock them up using this code
    Solution will be (my_id wallet_coin_primary_input wallet_coin_amount)
    """

    MOD = load_clvm("../puzzles/rl_aggregation.clvm")
    return MOD.curry(wallet_puzzle)
