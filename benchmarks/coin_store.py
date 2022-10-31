from __future__ import annotations

import asyncio
import os
import random
import sys
from pathlib import Path
from time import monotonic
from typing import List, Tuple

from utils import rand_hash, rewards, setup_db

from chia.full_node.coin_store import CoinStore
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint32, uint64

NUM_ITERS = 200

# we need seeded random, to have reproducible benchmark runs
random.seed(123456789)


def make_coin() -> Coin:
    return Coin(rand_hash(), rand_hash(), uint64(1))


def make_coins(num: int) -> Tuple[List[Coin], List[bytes32]]:
    additions: List[Coin] = []
    hashes: List[bytes32] = []
    for i in range(num):
        c = make_coin()
        additions.append(c)
        hashes.append(c.name())

    return additions, hashes


async def run_new_block_benchmark(version: int):

    verbose: bool = "--verbose" in sys.argv
    db_wrapper: DBWrapper2 = await setup_db("coin-store-benchmark.db", version)

    # keep track of benchmark total time
    all_test_time = 0.0

    try:
        coin_store = await CoinStore.create(db_wrapper)

        all_unspent: List[bytes32] = []
        all_coins: List[bytes32] = []

        block_height = 1
        timestamp = 1631794488

        print("Building database ", end="")
        for height in range(block_height, block_height + NUM_ITERS):

            # add some new coins
            additions, hashes = make_coins(2000)

            # farm rewards
            farmer_coin, pool_coin = rewards(uint32(height))
            all_coins += hashes
            all_unspent += hashes
            all_unspent += [pool_coin.name(), farmer_coin.name()]

            # remove some coins we've added previously
            random.shuffle(all_unspent)
            removals = all_unspent[:100]
            all_unspent = all_unspent[100:]

            await coin_store.new_block(
                uint32(height),
                uint64(timestamp),
                {pool_coin, farmer_coin},
                additions,
                removals,
            )

            # 19 seconds per block
            timestamp += 19

            if verbose:
                print(".", end="")
                sys.stdout.flush()
        block_height += NUM_ITERS

        total_time = 0.0
        total_add = 0.0
        total_remove = 0.0
        print("")
        if verbose:
            print("Profiling mostly additions ", end="")
        for height in range(block_height, block_height + NUM_ITERS):

            # add some new coins
            additions, hashes = make_coins(2000)
            total_add += 2000

            farmer_coin, pool_coin = rewards(uint32(height))
            all_coins += hashes
            all_unspent += hashes
            all_unspent += [pool_coin.name(), farmer_coin.name()]
            total_add += 2

            # remove some coins we've added previously
            random.shuffle(all_unspent)
            removals = all_unspent[:100]
            all_unspent = all_unspent[100:]
            total_remove += 100

            start = monotonic()
            await coin_store.new_block(
                uint32(height),
                uint64(timestamp),
                {pool_coin, farmer_coin},
                additions,
                removals,
            )
            stop = monotonic()

            # 19 seconds per block
            timestamp += 19

            total_time += stop - start
            if verbose:
                print(".", end="")
                sys.stdout.flush()

        block_height += NUM_ITERS

        if verbose:
            print("")
        print(f"{total_time:0.4f}s, MOSTLY ADDITIONS additions: {total_add} removals: {total_remove}")
        all_test_time += total_time

        if verbose:
            print("Profiling mostly removals ", end="")
        total_add = 0
        total_remove = 0
        total_time = 0
        for height in range(block_height, block_height + NUM_ITERS):
            additions = []

            # add one new coins
            c = make_coin()
            additions.append(c)
            total_add += 1

            farmer_coin, pool_coin = rewards(uint32(height))
            all_coins += [c.name()]
            all_unspent += [c.name()]
            all_unspent += [pool_coin.name(), farmer_coin.name()]
            total_add += 2

            # remove some coins we've added previously
            random.shuffle(all_unspent)
            removals = all_unspent[:700]
            all_unspent = all_unspent[700:]
            total_remove += 700

            start = monotonic()
            await coin_store.new_block(
                uint32(height),
                uint64(timestamp),
                {pool_coin, farmer_coin},
                additions,
                removals,
            )

            stop = monotonic()

            # 19 seconds per block
            timestamp += 19

            total_time += stop - start
            if verbose:
                print(".", end="")
                sys.stdout.flush()

        block_height += NUM_ITERS

        if verbose:
            print("")
        print(f"{total_time:0.4f}s, MOSTLY REMOVALS additions: {total_add} removals: {total_remove}")
        all_test_time += total_time

        if verbose:
            print("Profiling full block transactions", end="")
        total_add = 0
        total_remove = 0
        total_time = 0
        for height in range(block_height, block_height + NUM_ITERS):

            # add some new coins
            additions, hashes = make_coins(2000)
            total_add += 2000

            farmer_coin, pool_coin = rewards(uint32(height))
            all_coins += hashes
            all_unspent += hashes
            all_unspent += [pool_coin.name(), farmer_coin.name()]
            total_add += 2

            # remove some coins we've added previously
            random.shuffle(all_unspent)
            removals = all_unspent[:2000]
            all_unspent = all_unspent[2000:]
            total_remove += 2000

            start = monotonic()
            await coin_store.new_block(
                uint32(height),
                uint64(timestamp),
                {pool_coin, farmer_coin},
                additions,
                removals,
            )
            stop = monotonic()

            # 19 seconds per block
            timestamp += 19

            total_time += stop - start
            if verbose:
                print(".", end="")
                sys.stdout.flush()

        block_height += NUM_ITERS

        if verbose:
            print("")
        print(f"{total_time:0.4f}s, FULLBLOCKS additions: {total_add} removals: {total_remove}")
        all_test_time += total_time

        if verbose:
            print("profiling get_coin_records_by_names, include_spent ", end="")
        total_time = 0
        found_coins = 0
        for i in range(NUM_ITERS):
            lookup = random.sample(all_coins, 200)
            start = monotonic()
            records = await coin_store.get_coin_records_by_names(True, lookup)
            total_time += monotonic() - start
            assert len(records) == 200
            found_coins += len(records)
            if verbose:
                print(".", end="")
                sys.stdout.flush()

        if verbose:
            print("")
        print(
            f"{total_time:0.4f}s, GET RECORDS BY NAMES with spent {NUM_ITERS} "
            f"lookups found {found_coins} coins in total"
        )
        all_test_time += total_time

        if verbose:
            print("profiling get_coin_records_by_names, without spent coins ", end="")
        total_time = 0
        found_coins = 0
        for i in range(NUM_ITERS):
            lookup = random.sample(all_coins, 200)
            start = monotonic()
            records = await coin_store.get_coin_records_by_names(False, lookup)
            total_time += monotonic() - start
            assert len(records) <= 200
            found_coins += len(records)
            if verbose:
                print(".", end="")
                sys.stdout.flush()

        if verbose:
            print("")
        print(
            f"{total_time:0.4f}s, GET RECORDS BY NAMES without spent {NUM_ITERS} "
            f"lookups found {found_coins} coins in total"
        )
        all_test_time += total_time

        if verbose:
            print("profiling get_coin_removed_at_height ", end="")
        total_time = 0
        found_coins = 0
        for i in range(1, block_height):
            start = monotonic()
            records = await coin_store.get_coins_removed_at_height(uint32(i))
            total_time += monotonic() - start
            found_coins += len(records)
            if verbose:
                print(".", end="")
                sys.stdout.flush()

        if verbose:
            print("")
        print(
            f"{total_time:0.4f}s, GET COINS REMOVED AT HEIGHT {block_height-1} blocks, "
            f"found {found_coins} coins in total"
        )
        all_test_time += total_time
        print(f"all tests completed in {all_test_time:0.4f}s")

    finally:
        await db_wrapper.close()

    db_size = os.path.getsize(Path("coin-store-benchmark.db"))
    print(f"database size: {db_size/1000000:.3f} MB")


if __name__ == "__main__":
    print("version 1")
    asyncio.run(run_new_block_benchmark(1))
    print("version 2")
    asyncio.run(run_new_block_benchmark(2))
