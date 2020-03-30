import math
from binascii import hexlify

from clvm_tools import binutils

from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.util.ints import uint64


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
         min_block_time, parent_parent_id, parent_amount)
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

    opcode_aggsig = hexlify(ConditionOpcode.AGG_SIG).decode("ascii")
    opcode_coin_block_age = hexlify(ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS).decode(
        "ascii"
    )
    opcode_create = hexlify(ConditionOpcode.CREATE_COIN).decode("ascii")
    opcode_myid = hexlify(ConditionOpcode.ASSERT_MY_COIN_ID).decode("ascii")

    TEMPLATE_MY_PARENT_ID = "(sha256 (f (r (r (r (r (r (r (a)))))))) (f (r (a))) (f (r (r (r (r (r (r (r (a))))))))))"
    TEMPLATE_SINGLETON_RL = f'((c (i (i (= {TEMPLATE_MY_PARENT_ID} (f (a))) (q 1) (= (f (a)) (q 0x{origin_id}))) (q (c (q 1) (q ()))) (q (x (q "Parent doesnt satisfy RL conditions")))) (a)))'  # noqa: E501
    TEMPLATE_BLOCK_AGE = f'((c (i (i (= (* (f (r (r (r (r (r (a))))))) (q {rate_amount})) (* (f (r (r (r (r (a)))))) (q {interval_time}))) (q 1) (q (> (* (f (r (r (r (r (r (a))))))) (q {rate_amount})) (* (f (r (r (r (r (a))))))) (q {interval_time})))) (q (c (q 0x{opcode_coin_block_age}) (c (f (r (r (r (r (r (a))))))) (q ())))) (q (x (q "wrong min block time")))) (a) ))'  # noqa: E501
    TEMPLATE_MY_ID = f"(c (q 0x{opcode_myid}) (c (sha256 (f (a)) (f (r (a))) (f (r (r (a))))) (q ())))"  # noqa: E501
    CREATE_CHANGE = f"(c (q 0x{opcode_create}) (c (f (r (a))) (c (- (f (r (r (a)))) (f (r (r (r (r (a))))))) (q ()))))"  # noqa: E501
    CREATE_NEW_COIN = f"(c (q 0x{opcode_create}) (c (f (r (r (r (a))))) (c (f (r (r (r (r (a)))))) (q ()))))"  # noqa: E501
    RATE_LIMIT_PUZZLE = f"(c {TEMPLATE_SINGLETON_RL} (c {TEMPLATE_BLOCK_AGE} (c {CREATE_CHANGE} (c {TEMPLATE_MY_ID} (c {CREATE_NEW_COIN} (q ()))))))"  # noqa: E501

    TEMPLATE_MY_PARENT_ID_2 = "(sha256 (f (r (r (r (r (r (r (r (r (a)))))))))) (f (r (a))) (f (r (r (r (r (r (r (r (a))))))))))"  # noqa: E501
    TEMPLATE_SINGLETON_RL_2 = f'((c (i (i (= {TEMPLATE_MY_PARENT_ID_2} (f (r (r (r (r (r (a)))))))) (q 1) (= (f (r (r (r (r (r (a))))))) (q 0x{origin_id}))) (q (c (q 1) (q ()))) (q (x (q "Parent doesnt satisfy RL conditions")))) (a)))'  # noqa: E501
    CREATE_CONSOLIDATED = f"(c (q 0x{opcode_create}) (c (f (r (a))) (c (+ (f (r (r (r (r (a)))))) (f (r (r (r (r (r (r (a))))))))) (q ()))))"  # noqa: E501
    MODE_TWO_ME_STRING = f"(c (q 0x{opcode_myid}) (c (sha256 (f (r (r (r (r (r (a))))))) (f (r (a))) (f (r (r (r (r (r (r (a))))))))) (q ())))"  # noqa: E501
    CREATE_LOCK = f"(c (q 0x{opcode_create}) (c (sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (sha256 (f (r (r (a)))) (f (r (r (r (a))))) (f (r (r (r (r (a))))))) (q ()))) (c (q (q ())) (q ())))) (q ())))) (c (q 0) (q ()))))"  # noqa: E501

    MODE_TWO = f"(c {TEMPLATE_SINGLETON_RL_2} (c {MODE_TWO_ME_STRING} (c {CREATE_LOCK} (c {CREATE_CONSOLIDATED} (q ())))))"  # noqa: E501

    AGGSIG_ENTIRE_SOLUTION = (
        f"(c (q 0x{opcode_aggsig}) (c (q 0x{hex_pk}) (c (sha256tree (a)) (q ()))))"
    )

    WHOLE_PUZZLE = f"(c {AGGSIG_ENTIRE_SOLUTION} ((c (i (= (f (a)) (q 1)) (q ((c (q {RATE_LIMIT_PUZZLE}) (r (a))))) (q {MODE_TWO})) (a))) (q ()))"  # noqa: E501
    CLAWBACK = f"(c (c (q 0x{opcode_aggsig}) (c (q 0x{clawback_pk_str}) (c (sha256tree (a)) (q ())))) (r (a)))"
    WHOLE_PUZZLE_WITH_CLAWBACK = (
        f"((c (i (= (f (a)) (q 3)) (q {CLAWBACK}) (q {WHOLE_PUZZLE})) (a)))"
    )

    return Program(binutils.assemble(WHOLE_PUZZLE_WITH_CLAWBACK))


def rl_make_aggregation_solution(myid, wallet_coin_primary_input, wallet_coin_amount):
    opcode_myid = hexlify(myid).decode("ascii")
    primary_input = hexlify(wallet_coin_primary_input).decode("ascii")
    sol = f"(0x{opcode_myid} 0x{primary_input} {wallet_coin_amount})"
    return Program(binutils.assemble(sol))


def make_clawback_solution(puzzlehash, amount):
    opcode_create = hexlify(ConditionOpcode.CREATE_COIN).decode("ascii")
    solution = f"(3 (0x{opcode_create} 0x{puzzlehash} {amount}))"
    return Program(binutils.assemble(solution))


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
    consolidating_coin_puzzle_hash = hexlify(consolidating_coin_puzzle_hash).decode(
        "ascii"
    )
    primary_input = hexlify(my_primary_input).decode("ascii")
    sol = f"(2 0x{my_puzzle_hash} 0x{consolidating_primary_input} 0x{consolidating_coin_puzzle_hash} {outgoing_amount} 0x{primary_input} {incoming_amount} {parent_amount} 0x{my_parent_parent_id})"  # noqa: E501
    return Program(binutils.assemble(sol))


def solution_for_rl(
    my_parent_id,
    my_puzzlehash,
    my_amount,
    out_puzzlehash,
    out_amount,
    my_parent_parent_id,
    parent_amount,
    interval,
    limit,
):
    """
    Solution is (1 my_parent_id, my_puzzlehash, my_amount, outgoing_puzzle_hash, outgoing_amount,
    min_block_time, parent_parent_id, parent_amount)
    min block time = Math.ceil((new_amount * self.interval) / self.limit)
    """
    min_block_count = math.ceil((out_amount * interval) / limit)
    solution = (
        f"(1 0x{my_parent_id} 0x{my_puzzlehash} {my_amount} 0x{out_puzzlehash} {out_amount}"
        f" {min_block_count} 0x{my_parent_parent_id} {parent_amount})"
    )
    return Program(binutils.assemble(solution))


def rl_make_aggregation_puzzle(wallet_puzzle):
    """
     If Wallet A wants to send further funds to Wallet B then they can lock them up using this code
     Solution will be (my_id wallet_coin_primary_input wallet_coin_amount)
    """
    opcode_myid = hexlify(ConditionOpcode.ASSERT_MY_COIN_ID).decode("ascii")
    opcode_consumed = hexlify(ConditionOpcode.ASSERT_COIN_CONSUMED).decode("ascii")
    me_is_my_id = f"(c (q 0x{opcode_myid}) (c (f (a)) (q ())))"

    # lock_puzzle is the hash of '(r (c (q "merge in ID") (q ())))'
    lock_puzzle = "(sha256tree (c (q 7) (c (c (q 5) (c (c (q 1) (c (f (a)) (q ()))) (c (q (q ())) (q ())))) (q ()))))"
    parent_coin_id = f"(sha256 (f (r (a))) (q 0x{wallet_puzzle}) (f (r (r (a)))))"
    input_of_lock = f"(c (q 0x{opcode_consumed}) (c (sha256 {parent_coin_id} {lock_puzzle} (q 0)) (q ())))"
    puz = f"(c {me_is_my_id} (c {input_of_lock} (q ())))"

    return Program(binutils.assemble(puz))
