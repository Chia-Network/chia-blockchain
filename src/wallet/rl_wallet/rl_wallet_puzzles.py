import math
from binascii import hexlify

from clvm_tools import binutils

from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.wallet.chialisp import (
    eval,
    sexp,
    sha256,
    args,
    make_if,
    iff,
    equal,
    quote,
    hexstr,
    fail,
    multiply,
    greater,
    make_list,
    subtract,
    add,
    sha256tree,
    cons,
    rest,
    string,
)


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

    hex_pk = pubkey.hex()
    clawback_pk_str = clawback_pk.hex()
    origin_id = origin_id.hex()

    opcode_aggsig = ConditionOpcode.AGG_SIG.hex()
    opcode_coin_block_age = ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS.hex()
    opcode_create = ConditionOpcode.CREATE_COIN.hex()
    opcode_myid = ConditionOpcode.ASSERT_MY_COIN_ID.hex()

    TEMPLATE_MY_PARENT_ID = sha256(args(6), args(1), args(7))
    TEMPLATE_SINGLETON_RL = make_if(
        iff(
            equal(TEMPLATE_MY_PARENT_ID, args(0)),
            quote(1),
            equal(args(0), hexstr(origin_id)),
        ),
        sexp(),
        fail(quote(string("Parent doesnt satisfy RL conditions"))),
    )
    TEMPLATE_BLOCK_AGE = make_if(
        iff(
            equal(
                multiply(args(5), quote(rate_amount)),
                multiply(args(4), quote(interval_time)),
            ),
            quote(1),
            quote(
                greater(
                    multiply(args(5), quote(rate_amount)),
                    multiply(args(4)),  # multiply looks wrong
                    quote(interval_time),
                )
            ),
        ),
        make_list(hexstr(opcode_coin_block_age), args(5)),
        fail(string("wrong min block time")),
    )
    TEMPLATE_MY_ID = make_list(hexstr(opcode_myid), sha256(args(0), args(1), args(2)))
    CREATE_CHANGE = make_list(hexstr(opcode_create), args(1), subtract(args(2), add(args(4), args(8))))
    CREATE_NEW_COIN = make_list(hexstr(opcode_create), args(3), args(4))
    RATE_LIMIT_PUZZLE = make_if(
        TEMPLATE_SINGLETON_RL,
        make_list(
            TEMPLATE_SINGLETON_RL,
            TEMPLATE_BLOCK_AGE,
            CREATE_CHANGE,
            TEMPLATE_MY_ID,
            CREATE_NEW_COIN,
        ),
        make_list(
            TEMPLATE_BLOCK_AGE,
            CREATE_CHANGE,
            TEMPLATE_MY_ID,
            CREATE_NEW_COIN,
        ),
    )

    TEMPLATE_MY_PARENT_ID_2 = sha256(args(8), args(1), args(7))
    TEMPLATE_SINGLETON_RL_2 = make_if(
        iff(
            equal(TEMPLATE_MY_PARENT_ID_2, args(5)),
            quote(1),
            equal(hexstr(origin_id), args(5)),
        ),
        sexp(),
        fail(quote(string("Parent doesnt satisfy RL conditions"))),
    )
    CREATE_CONSOLIDATED = make_list(hexstr(opcode_create), args(1), (add(args(4), args(6))))
    MODE_TWO_ME_STRING = make_list(hexstr(opcode_myid), sha256(args(5), args(1), args(6)))
    CREATE_LOCK = make_list(
        hexstr(opcode_create),
        sha256tree(
            make_list(
                quote(7),
                make_list(
                    quote(5),
                    make_list(quote(1), sha256(args(2), args(3), args(4))),
                    quote(make_list()),
                ),
            )
        ),  # why?
        quote(0),
    )
    MODE_TWO = make_if(
        TEMPLATE_SINGLETON_RL_2,
        make_list(
            TEMPLATE_SINGLETON_RL_2,
            MODE_TWO_ME_STRING,
            CREATE_LOCK,
            CREATE_CONSOLIDATED,
        ),
        make_list(MODE_TWO_ME_STRING, CREATE_LOCK, CREATE_CONSOLIDATED),
    )
    AGGSIG_ENTIRE_SOLUTION = make_list(hexstr(opcode_aggsig), hexstr(hex_pk), sha256tree(args()))
    WHOLE_PUZZLE = cons(
        AGGSIG_ENTIRE_SOLUTION,
        make_if(
            equal(args(0), quote(1)),
            eval(quote(RATE_LIMIT_PUZZLE), rest(args())),
            MODE_TWO,
        ),
    )
    CLAWBACK = cons(
        make_list(hexstr(opcode_aggsig), hexstr(clawback_pk_str), sha256tree(args())),
        rest(args()),
    )

    WHOLE_PUZZLE_WITH_CLAWBACK = make_if(equal(args(0), quote(3)), CLAWBACK, WHOLE_PUZZLE)

    return Program.to(binutils.assemble(WHOLE_PUZZLE_WITH_CLAWBACK))


def rl_make_aggregation_solution(myid, wallet_coin_primary_input, wallet_coin_amount):
    opcode_myid = "0x" + hexlify(myid).decode("ascii")
    primary_input = "0x" + hexlify(wallet_coin_primary_input).decode("ascii")
    sol = sexp(opcode_myid, primary_input, wallet_coin_amount)
    return Program.to(binutils.assemble(sol))


def make_clawback_solution(puzzlehash, amount, fee):
    opcode_create = hexlify(ConditionOpcode.CREATE_COIN).decode("ascii")
    solution = sexp(3, sexp("0x" + opcode_create, "0x" + str(puzzlehash), amount - fee))
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
        2,
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
        1,
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
    opcode_myid = hexlify(ConditionOpcode.ASSERT_MY_COIN_ID).decode("ascii")
    opcode_consumed = hexlify(ConditionOpcode.ASSERT_COIN_CONSUMED).decode("ascii")
    me_is_my_id = make_list(hexstr(opcode_myid), args(0))

    # lock_puzzle is the hash of '(r (c (q "merge in ID") (q ())))'
    lock_puzzle = sha256tree(
        make_list(
            quote(7),
            make_list(quote(5), make_list(quote(1), args(0)), quote(quote(sexp()))),
        )
    )
    parent_coin_id = sha256(args(1), hexstr(wallet_puzzle), args(2))
    input_of_lock = make_list(hexstr(opcode_consumed), sha256(parent_coin_id, lock_puzzle, quote(0)))
    puz = make_list(me_is_my_id, input_of_lock)

    return Program.to(binutils.assemble(puz))
