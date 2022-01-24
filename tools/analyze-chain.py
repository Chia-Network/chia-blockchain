#!/usr/bin/env python3

import sqlite3
import sys
from typing import List
from time import time

from clvm_rs import run_generator
from clvm import KEYWORD_FROM_ATOM, KEYWORD_TO_ATOM
from clvm.casts import int_from_bytes
from clvm.operators import OP_REWRITE

from chia.types.full_block import FullBlock
from chia.types.blockchain_format.program import Program
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.wallet.puzzles.rom_bootstrap_generator import get_generator
from chia.types.condition_opcodes import ConditionOpcode

GENERATOR_ROM = bytes(get_generator())

native_opcode_names_by_opcode = dict(
    ("op_%s" % OP_REWRITE.get(k, k), op) for op, k in KEYWORD_FROM_ATOM.items() if k not in "qa."
)


def run_gen(env_data: bytes, block_program_args: bytes):
    max_cost = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM
    cost_per_byte = DEFAULT_CONSTANTS.COST_PER_BYTE

    # we don't charge for the size of the generator ROM. However, we do charge
    # cost for the operations it executes
    max_cost -= len(env_data) * cost_per_byte

    env_data = b"\xff" + env_data + b"\xff" + block_program_args + b"\x80"

    try:
        return run_generator(
            GENERATOR_ROM,
            env_data,
            KEYWORD_TO_ATOM["q"][0],
            KEYWORD_TO_ATOM["a"][0],
            native_opcode_names_by_opcode,
            max_cost,
            0,
        )
    except Exception as e:
        # GENERATOR_RUNTIME_ERROR
        print(f"Exception: {e}")
        return (117, [], None)


cond_map = {
    ConditionOpcode.AGG_SIG_UNSAFE[0]: 0,
    ConditionOpcode.AGG_SIG_ME[0]: 1,
    ConditionOpcode.CREATE_COIN[0]: 2,
    ConditionOpcode.RESERVE_FEE[0]: 3,
    ConditionOpcode.CREATE_COIN_ANNOUNCEMENT[0]: 4,
    ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT[0]: 5,
    ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT[0]: 6,
    ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT[0]: 7,
    ConditionOpcode.ASSERT_MY_COIN_ID[0]: 8,
    ConditionOpcode.ASSERT_MY_PARENT_ID[0]: 9,
    ConditionOpcode.ASSERT_MY_PUZZLEHASH[0]: 10,
    ConditionOpcode.ASSERT_MY_AMOUNT[0]: 11,
    ConditionOpcode.ASSERT_SECONDS_RELATIVE[0]: 12,
    ConditionOpcode.ASSERT_SECONDS_ABSOLUTE[0]: 13,
    ConditionOpcode.ASSERT_HEIGHT_RELATIVE[0]: 14,
    ConditionOpcode.ASSERT_HEIGHT_ABSOLUTE[0]: 15,
}

c = sqlite3.connect(sys.argv[1])

rows = c.execute("SELECT header_hash, height, block FROM full_blocks ORDER BY height")

height_to_hash: List[bytes] = []

for r in rows:
    hh = bytes.fromhex(r[0])
    height = r[1]
    block = FullBlock.from_bytes(r[2])

    if len(height_to_hash) <= height:
        assert len(height_to_hash) == height
        height_to_hash.append(hh)
    else:
        height_to_hash[height] = hh

    if height > 0:
        prev_hh = block.prev_header_hash
        h = height - 1
        while height_to_hash[h] != prev_hh:
            height_to_hash[h] = prev_hh
            ref = c.execute("SELECT block FROM full_blocks WHERE header_hash=?", (prev_hh.hex(),))
            ref_block = FullBlock.from_bytes(ref.fetchone()[0])
            prev_hh = ref_block.prev_header_hash
            h -= 1
            if h < 0:
                break

    if block.transactions_generator is None:
        continue

    # add the block program arguments
    block_program_args = bytearray(b"\xff")

    num_refs = 0
    for h in block.transactions_generator_ref_list:
        ref = c.execute("SELECT block FROM full_blocks WHERE header_hash=?", (height_to_hash[h].hex(),))
        ref_block = FullBlock.from_bytes(ref.fetchone()[0])
        block_program_args += b"\xff"
        block_program_args += Program.to(bytes(ref_block.transactions_generator)).as_bin()
        num_refs += 1
        ref.close()

    block_program_args += b"\x80\x80"

    start_time = time()
    err, result, cost = run_gen(bytes(block.transactions_generator), bytes(block_program_args))
    run_time = time() - start_time
    if err is not None:
        print(f"ERROR: {hh.hex()} {height} {err}")
        break

    num_removals = 0
    fees = 0
    conditions = [0] * 16
    for res in result:
        num_removals += 1
        for cond in res.conditions:
            for cwa in cond[1]:
                if cwa.opcode == ConditionOpcode.RESERVE_FEE[0]:
                    fees += int_from_bytes(cwa.vars[0])
                conditions[cond_map[cwa.opcode]] += 1

    print(
        f"{hh.hex()}\t{height}\t{cost}\t{run_time:0.3f}\t{num_refs}\t{fees}\t"
        f"{len(bytes(block.transactions_generator))}\t"
        f"{num_removals}\t" + "\t".join([f"{cond}" for cond in conditions])
    )
