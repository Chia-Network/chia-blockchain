from __future__ import annotations

import cProfile
import sqlite3
import sys
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

import click
import zstd
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.util.constants import test_constants
from chia.simulator.block_tools import create_block_tools
from chia.simulator.keyring import TempKeyring
from chia.util.chia_logging import initialize_logging


@contextmanager
def enable_profiler(profile: bool, counter: int) -> Iterator[None]:
    if not profile:
        yield
        return

    with cProfile.Profile() as pr:
        yield

    pr.create_stats()
    pr.dump_stats(f"generate-chain-{counter}.profile")


@click.command()
@click.option("--length", type=int, default=None, required=False, help="the number of blocks to generate")
@click.option("--profile", is_flag=True, required=False, default=False, help="dump CPU profile at the end")
@click.option(
    "--output", type=str, required=False, default=None, help="the filename to write the resulting sqlite database to"
)
def main(length: int, profile: bool, output: str | None) -> None:
    if not length:
        length = 500

    if length <= 0:
        print("the output blockchain must have at least length 1")
        sys.exit(1)

    if output is None:
        output = f"stress-test-blockchain-{length}.sqlite"

    root_path = Path("./test-chain").resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    tc = test_constants.replace(HARD_FORK_HEIGHT=uint32(0))
    with (
        TempKeyring() as keychain,
        create_block_tools(constants=tc, root_path=root_path, keychain=keychain) as bt,
    ):
        initialize_logging(
            "generate_chain", {"log_level": "DEBUG", "log_stdout": False, "log_syslog": False}, root_path=root_path
        )
        farmer_puzzlehash: bytes32 = bt.farmer_ph
        pool_puzzlehash: bytes32 = bt.farmer_ph
        num_unspent: int = 0
        num_spends: int = bt.prev_num_spends
        num_additions: int = bt.prev_num_additions

        print(f"writing blockchain to {output}")
        with closing(sqlite3.connect(output)) as db:
            db.execute(
                "CREATE TABLE full_blocks("
                "header_hash blob PRIMARY KEY,"
                "prev_hash blob,"
                "height bigint,"
                "in_main_chain tinyint,"
                "block blob)"
            )

            transaction_blocks: list[uint32] = []

            blocks = bt.get_consecutive_blocks(
                3,
                farmer_reward_puzzle_hash=farmer_puzzlehash,
                pool_reward_puzzle_hash=pool_puzzlehash,
                keep_going_until_tx_block=True,
                genesis_timestamp=uint64(1234567890),
            )

            for b in blocks:
                db.execute(
                    "INSERT INTO full_blocks VALUES(?, ?, ?, ?, ?)",
                    (
                        b.header_hash,
                        b.prev_header_hash,
                        b.height,
                        1,  # in_main_chain
                        zstd.compress(bytes(b)),
                    ),
                )
            db.commit()

            b = blocks[-1]

            while True:
                with enable_profiler(profile, b.height):
                    start_time = time.monotonic()

                    prev_num_blocks = len(blocks)
                    blocks = bt.get_consecutive_blocks(
                        1,
                        blocks,
                        farmer_reward_puzzle_hash=farmer_puzzlehash,
                        pool_reward_puzzle_hash=pool_puzzlehash,
                        keep_going_until_tx_block=True,
                        include_transactions=2,
                    )
                    prev_tx_block = b
                    prev_block = blocks[-2]
                    b = blocks[-1]
                    height = b.height
                    assert b.is_transaction_block()
                    transaction_blocks.append(height)
                    num_spends += bt.prev_num_spends
                    num_additions += bt.prev_num_additions
                    num_unspent = num_unspent + bt.prev_num_additions - bt.prev_num_spends

                    if b.transactions_info:
                        if b.transactions_info.cost > tc.MAX_BLOCK_COST_CLVM:
                            print(f"COST EXCEEDED: {b.transactions_info.cost}")

                    end_time = time.monotonic()
                    if prev_tx_block is not None:
                        assert b.foliage_transaction_block
                        assert prev_tx_block.foliage_transaction_block
                        ts = b.foliage_transaction_block.timestamp - prev_tx_block.foliage_transaction_block.timestamp
                    else:
                        ts = 0

                    print(
                        f"height: {b.height} "
                        f"spends: {num_spends} "
                        f"new coins: {num_additions} "
                        f"unspent: {num_unspent} "
                        f"difficulty: {b.weight - prev_block.weight} "
                        f"timestamp: {ts} "
                        f"time: {end_time - start_time:0.2f}s "
                        f"tx-block-ratio: {len(transaction_blocks) * 100 / b.height:0.0f}% "
                    )

                    new_blocks = [
                        (
                            b.header_hash,
                            b.prev_header_hash,
                            b.height,
                            1,  # in_main_chain
                            zstd.compress(bytes(b)),
                        )
                        for b in blocks[prev_num_blocks:]
                    ]
                    db.executemany("INSERT INTO full_blocks VALUES(?, ?, ?, ?, ?)", new_blocks)
                    db.commit()
                    if height >= length:
                        break


if __name__ == "__main__":
    main()
