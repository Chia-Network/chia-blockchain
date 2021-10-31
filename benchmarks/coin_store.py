import asyncio
import random
import secrets
from time import time
from pathlib import Path
from chia.full_node.coin_store import CoinStore
from typing import List, Tuple
import os
import sys

import aiosqlite
from chia.util.db_wrapper import DBWrapper
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.util.ints import uint64, uint32


NUM_ITERS = 200

# farmer puzzle hash
ph = bytes32(b"a" * 32)


async def setup_db() -> DBWrapper:
    db_filename = Path("coin-store-benchmark.db")
    try:
        os.unlink(db_filename)
    except FileNotFoundError:
        pass
    connection = await aiosqlite.connect(db_filename)
    await connection.execute("pragma journal_mode=wal")
    await connection.execute("pragma synchronous=FULL")
    return DBWrapper(connection)


def rand_hash() -> bytes32:
    return secrets.token_bytes(32)


def make_coin() -> Coin:
    return Coin(rand_hash(), rand_hash(), uint64(1))


def make_coins(num: int) -> Tuple[List[Coin], List[bytes32]]:
    additions: List[Coin] = []
    hashes: List[bytes32] = []
    for i in range(num):
        c = make_coin()
        additions.append(c)
        hashes.append(c.get_hash())

    return additions, hashes


def rewards(height: uint32) -> Tuple[Coin, Coin]:
    farmer_coin = create_farmer_coin(height, ph, uint64(250000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    pool_coin = create_pool_coin(height, ph, uint64(1750000000), DEFAULT_CONSTANTS.GENESIS_CHALLENGE)
    return farmer_coin, pool_coin


async def run_new_block_benchmark():

    db_wrapper: DBWrapper = await setup_db()

    verbose: bool = "--verbose" in sys.argv
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
            farmer_coin, pool_coin = rewards(height)
            all_coins += hashes
            all_unspent += hashes
            all_unspent += [pool_coin.name(), farmer_coin.name()]

            # remove some coins we've added previously
            random.shuffle(all_unspent)
            removals = all_unspent[:100]
            all_unspent = all_unspent[100:]

            await coin_store.new_block(
                height,
                timestamp,
                set([pool_coin, farmer_coin]),
                additions,
                removals,
            )
            await db_wrapper.db.commit()

            # 19 seconds per block
            timestamp += 19

            if verbose:
                print(".", end="")
                sys.stdout.flush()
        block_height += NUM_ITERS

        total_time = 0
        total_add = 0
        total_remove = 0
        print("")
        if verbose:
            print("Profiling mostly additions ", end="")
        for height in range(block_height, block_height + NUM_ITERS):

            # add some new coins
            additions, hashes = make_coins(2000)
            total_add += 2000

            farmer_coin, pool_coin = rewards(height)
            all_coins += hashes
            all_unspent += hashes
            all_unspent += [pool_coin.name(), farmer_coin.name()]
            total_add += 2

            # remove some coins we've added previously
            random.shuffle(all_unspent)
            removals = all_unspent[:100]
            all_unspent = all_unspent[100:]
            total_remove += 100

            start = time()
            await coin_store.new_block(
                height,
                timestamp,
                set([pool_coin, farmer_coin]),
                additions,
                removals,
            )
            await db_wrapper.db.commit()
            stop = time()

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

            farmer_coin, pool_coin = rewards(height)
            all_coins += [c.get_hash()]
            all_unspent += [c.get_hash()]
            all_unspent += [pool_coin.name(), farmer_coin.name()]
            total_add += 2

            # remove some coins we've added previously
            random.shuffle(all_unspent)
            removals = all_unspent[:700]
            all_unspent = all_unspent[700:]
            total_remove += 700

            start = time()
            await coin_store.new_block(
                height,
                timestamp,
                set([pool_coin, farmer_coin]),
                additions,
                removals,
            )
            await db_wrapper.db.commit()

            stop = time()

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

        if verbose:
            print("Profiling full block transactions", end="")
        total_add = 0
        total_remove = 0
        total_time = 0
        for height in range(block_height, block_height + NUM_ITERS):

            # add some new coins
            additions, hashes = make_coins(2000)
            total_add += 2000

            farmer_coin, pool_coin = rewards(height)
            all_coins += hashes
            all_unspent += hashes
            all_unspent += [pool_coin.name(), farmer_coin.name()]
            total_add += 2

            # remove some coins we've added previously
            random.shuffle(all_unspent)
            removals = all_unspent[:2000]
            all_unspent = all_unspent[2000:]
            total_remove += 2000

            start = time()
            await coin_store.new_block(
                height,
                timestamp,
                set([pool_coin, farmer_coin]),
                additions,
                removals,
            )
            await db_wrapper.db.commit()
            stop = time()

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

        if verbose:
            print("profiling get_coin_records_by_names, include_spent ", end="")
        total_time = 0
        found_coins = 0
        for i in range(NUM_ITERS):
            lookup = random.sample(all_coins, 200)
            start = time()
            records = await coin_store.get_coin_records_by_names(True, lookup)
            total_time += time() - start
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

        if verbose:
            print("profiling get_coin_records_by_names, without spent coins ", end="")
        total_time = 0
        found_coins = 0
        for i in range(NUM_ITERS):
            lookup = random.sample(all_coins, 200)
            start = time()
            records = await coin_store.get_coin_records_by_names(False, lookup)
            total_time += time() - start
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

        if verbose:
            print("profiling get_coin_removed_at_height ", end="")
        total_time = 0
        found_coins = 0
        for i in range(1, block_height):
            start = time()
            records = await coin_store.get_coins_removed_at_height(i)
            total_time += time() - start
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

    finally:
        await db_wrapper.db.close()


if __name__ == "__main__":
    asyncio.run(run_new_block_benchmark())
