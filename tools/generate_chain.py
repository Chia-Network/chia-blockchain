from __future__ import annotations

import cProfile
import random
import sqlite3
import sys
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator, List, Optional

import click
import zstd

from chia.simulator.block_tools import create_block_tools
from chia.types.blockchain_format.coin import Coin
from chia.types.spend_bundle import SpendBundle
from chia.util.chia_logging import initialize_logging
from chia.util.ints import uint32, uint64
from tests.util.keyring import TempKeyring
from tools.test_constants import test_constants


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
@click.option(
    "--fill-rate",
    type=int,
    default=100,
    required=False,
    help="the transaction fill rate of blocks. Specified in percent of max block cost",
)
@click.option("--profile", is_flag=True, required=False, default=False, help="dump CPU profile at the end")
@click.option(
    "--block-refs",
    type=bool,
    required=False,
    default=True,
    help="include a long list of block references in each transaction block",
)
@click.option(
    "--output", type=str, required=False, default=None, help="the filename to write the resulting sqlite database to"
)
def main(length: int, fill_rate: int, profile: bool, block_refs: bool, output: Optional[str]) -> None:

    if fill_rate < 0 or fill_rate > 100:
        print("fill-rate must be within [0, 100]")
        sys.exit(1)

    if not length:
        if block_refs:
            # we won't have full reflist until after 512 transaction blocks
            length = 1500
        else:
            # the cost of looking up coins will be deflated because there are so
            # few, but a longer chain takes longer to make and test
            length = 500

    if length <= 0:
        print("the output blockchain must have at least length 1")
        sys.exit(1)

    if output is None:
        output = f"stress-test-blockchain-{length}-{fill_rate}{'-refs' if block_refs else ''}.sqlite"

    root_path = Path("./test-chain").resolve()
    root_path.mkdir(parents=True, exist_ok=True)
    with TempKeyring() as keychain:

        bt = create_block_tools(constants=test_constants, root_path=root_path, keychain=keychain)
        initialize_logging(
            "generate_chain", {"log_level": "DEBUG", "log_stdout": False, "log_syslog": False}, root_path=root_path
        )

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

            wallet = bt.get_farmer_wallet_tool()
            farmer_puzzlehash = wallet.get_new_puzzlehash()
            pool_puzzlehash = wallet.get_new_puzzlehash()
            transaction_blocks: List[uint32] = []

            blocks = bt.get_consecutive_blocks(
                3,
                farmer_reward_puzzle_hash=farmer_puzzlehash,
                pool_reward_puzzle_hash=pool_puzzlehash,
                keep_going_until_tx_block=True,
                genesis_timestamp=uint64(1234567890),
                use_timestamp_residual=True,
            )

            unspent_coins: List[Coin] = []

            for b in blocks:
                for coin in b.get_included_reward_coins():
                    if coin.puzzle_hash in [farmer_puzzlehash, pool_puzzlehash]:
                        unspent_coins.append(coin)
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

            num_tx_per_block = int(1010 * fill_rate / 100)

            while True:
                with enable_profiler(profile, b.height):
                    start_time = time.monotonic()

                    new_coins: List[Coin] = []
                    spend_bundles: List[SpendBundle] = []
                    i = 0
                    for i in range(num_tx_per_block):
                        if unspent_coins == []:
                            break
                        c = unspent_coins.pop(random.randrange(len(unspent_coins)))
                        receiver = wallet.get_new_puzzlehash()
                        bundle = wallet.generate_signed_transaction(uint64(c.amount // 2), receiver, c)
                        new_coins.extend(bundle.additions())
                        spend_bundles.append(bundle)

                    block_references: List[uint32]
                    if block_refs:
                        block_references = random.sample(transaction_blocks, min(len(transaction_blocks), 512))
                        random.shuffle(block_references)
                    else:
                        block_references = []

                    farmer_puzzlehash = wallet.get_new_puzzlehash()
                    pool_puzzlehash = wallet.get_new_puzzlehash()
                    prev_num_blocks = len(blocks)
                    blocks = bt.get_consecutive_blocks(
                        1,
                        blocks,
                        farmer_reward_puzzle_hash=farmer_puzzlehash,
                        pool_reward_puzzle_hash=pool_puzzlehash,
                        keep_going_until_tx_block=True,
                        transaction_data=SpendBundle.aggregate(spend_bundles),
                        previous_generator=block_references,
                        use_timestamp_residual=True,
                    )
                    prev_tx_block = b
                    prev_block = blocks[-2]
                    b = blocks[-1]
                    height = b.height
                    assert b.is_transaction_block()
                    transaction_blocks.append(height)

                    for bl in blocks[prev_num_blocks:]:
                        for coin in bl.get_included_reward_coins():
                            unspent_coins.append(coin)
                    unspent_coins.extend(new_coins)

                    if b.transactions_info:
                        actual_fill_rate = b.transactions_info.cost / test_constants.MAX_BLOCK_COST_CLVM
                        if b.transactions_info.cost > test_constants.MAX_BLOCK_COST_CLVM:
                            print(f"COST EXCEEDED: {b.transactions_info.cost}")
                    else:
                        actual_fill_rate = 0

                    end_time = time.monotonic()
                    if prev_tx_block is not None:
                        assert b.foliage_transaction_block
                        assert prev_tx_block.foliage_transaction_block
                        ts = b.foliage_transaction_block.timestamp - prev_tx_block.foliage_transaction_block.timestamp
                    else:
                        ts = 0

                    print(
                        f"height: {b.height} "
                        f"spends: {i+1} "
                        f"refs: {len(block_references)} "
                        f"fill_rate: {actual_fill_rate*100:.1f}% "
                        f"new coins: {len(new_coins)} "
                        f"unspent: {len(unspent_coins)} "
                        f"difficulty: {b.weight - prev_block.weight} "
                        f"timestamp: {ts} "
                        f"time: {end_time - start_time:0.2f}s "
                        f"tx-block-ratio: {len(transaction_blocks)*100/b.height:0.0f}% "
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
    # pylint: disable = no-value-for-parameter
    main()
