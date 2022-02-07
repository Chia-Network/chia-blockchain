#!/usr/bin/env python3

import sqlite3
import sys
import zstd
import click
from pathlib import Path

from typing import List
from time import time


from clvm_rs import run_generator2, MEMPOOL_MODE

from chia.types.full_block import FullBlock
from chia.types.blockchain_format.program import Program
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.wallet.puzzles.rom_bootstrap_generator import get_generator
from chia.util.ints import uint32

GENERATOR_ROM = bytes(get_generator())


# returns an optional error code and an optional PySpendBundleConditions (from clvm_rs)
# exactly one of those will hold a value and the number of seconds it took to
# run
def run_gen(env_data: bytes, block_program_args: bytes, flags: uint32):
    max_cost = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM
    cost_per_byte = DEFAULT_CONSTANTS.COST_PER_BYTE

    # we don't charge for the size of the generator ROM. However, we do charge
    # cost for the operations it executes
    max_cost -= len(env_data) * cost_per_byte

    env_data = b"\xff" + env_data + b"\xff" + block_program_args + b"\x80"

    try:
        start_time = time()
        err, result = run_generator2(
            GENERATOR_ROM,
            env_data,
            max_cost,
            flags,
        )
        run_time = time() - start_time
        return err, result, run_time
    except Exception as e:
        # GENERATOR_RUNTIME_ERROR
        sys.stderr.write(f"Exception: {e}\n")
        return 117, None, 0


@click.command()
@click.argument("file", type=click.Path(), required=True)
@click.option(
    "--mempool-mode", default=False, is_flag=True, help="execute all block generators in the strict mempool mode"
)
def main(file: Path, mempool_mode: bool):
    c = sqlite3.connect(file)

    rows = c.execute("SELECT header_hash, height, block FROM full_blocks ORDER BY height")

    height_to_hash: List[bytes] = []

    for r in rows:
        hh: bytes = r[0]
        height = r[1]
        block = FullBlock.from_bytes(zstd.decompress(r[2]))

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
                ref = c.execute("SELECT block FROM full_blocks WHERE header_hash=?", (prev_hh,))
                ref_block = FullBlock.from_bytes(zstd.decompress(ref.fetchone()[0]))
                prev_hh = ref_block.prev_header_hash
                h -= 1
                if h < 0:
                    break

        if block.transactions_generator is None:
            sys.stderr.write(f" no-generator. block {height}\r")
            continue

        # add the block program arguments
        block_program_args = bytearray(b"\xff")

        num_refs = 0
        start_time = time()
        for h in block.transactions_generator_ref_list:
            ref = c.execute("SELECT block FROM full_blocks WHERE header_hash=?", (height_to_hash[h],))
            ref_block = FullBlock.from_bytes(zstd.decompress(ref.fetchone()[0]))
            block_program_args += b"\xff"
            block_program_args += Program.to(bytes(ref_block.transactions_generator)).as_bin()
            num_refs += 1
            ref.close()
        ref_lookup_time = time() - start_time

        block_program_args += b"\x80\x80"

        if mempool_mode:
            flags = MEMPOOL_MODE
        else:
            flags = 0
        err, result, run_time = run_gen(bytes(block.transactions_generator), bytes(block_program_args), flags)
        if err is not None:
            sys.stderr.write(f"ERROR: {hh.hex()} {height} {err}\n")
            break

        num_removals = len(result.spends)
        fees = result.reserve_fee
        cost = result.cost
        num_additions = 0
        for spends in result.spends:
            num_additions += len(spends.create_coin)

        print(
            f"{hh.hex()}\t{height}\t{cost}\t{run_time:0.3f}\t{num_refs}\t{ref_lookup_time:0.3f}\t{fees}\t"
            f"{len(bytes(block.transactions_generator))}\t"
            f"{num_removals}\t{num_additions}"
        )


if __name__ == "__main__":
    # pylint: disable = no-value-for-parameter
    main()
