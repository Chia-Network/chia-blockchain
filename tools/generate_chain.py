import cProfile
import random
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator, List

import zstd

from chia.types.blockchain_format.coin import Coin
from chia.types.spend_bundle import SpendBundle
from chia.util.chia_logging import initialize_logging
from chia.util.ints import uint64
from chia.util.path import mkdir
from tests.block_tools import create_block_tools
from tests.util.keyring import TempKeyring
from tools.test_constants import test_constants


@contextmanager
def enable_profiler(profile: bool) -> Iterator[None]:
    if not profile:
        yield
        return

    with cProfile.Profile() as pr:
        yield

    pr.create_stats()
    pr.dump_stats("generate-chain.profile")


root_path = Path("./test-chain").resolve()
mkdir(root_path)
with TempKeyring() as keychain:

    bt = create_block_tools(constants=test_constants, root_path=root_path, keychain=keychain)
    initialize_logging(
        "generate_chain", {"log_level": "DEBUG", "log_stdout": False, "log_syslog": False}, root_path=root_path
    )

    with closing(sqlite3.connect("stress-test-blockchain.sqlite")) as db:

        print("initializing v2 block store")
        db.execute(
            "CREATE TABLE full_blocks("
            "header_hash blob PRIMARY KEY,"
            "prev_hash blob,"
            "height bigint,"
            "in_main_chain tinyint,"
            "block blob)"
        )

        wallet = bt.get_farmer_wallet_tool()
        coinbase_puzzlehash = wallet.get_new_puzzlehash()

        blocks = bt.get_consecutive_blocks(
            3,
            farmer_reward_puzzle_hash=coinbase_puzzlehash,
            pool_reward_puzzle_hash=coinbase_puzzlehash,
            guarantee_transaction_block=True,
            genesis_timestamp=uint64(1234567890),
            time_per_block=30,
        )

        unspent_coins: List[Coin] = []

        for b in blocks:
            for coin in b.get_included_reward_coins():
                if coin.puzzle_hash == coinbase_puzzlehash:
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

        # build 2000 transaction blocks
        with enable_profiler(False):
            for k in range(2000):

                start_time = time.monotonic()

                print(f"block: {len(blocks)} unspent: {len(unspent_coins)}")
                new_coins: List[Coin] = []
                spend_bundles: List[SpendBundle] = []
                for i in range(1010):
                    if unspent_coins == []:
                        break
                    c = unspent_coins.pop(random.randrange(len(unspent_coins)))
                    receiver = wallet.get_new_puzzlehash()
                    bundle = wallet.generate_signed_transaction(uint64(c.amount // 2), receiver, c)
                    new_coins.extend(bundle.additions())
                    spend_bundles.append(bundle)

                coinbase_puzzlehash = wallet.get_new_puzzlehash()
                blocks = bt.get_consecutive_blocks(
                    1,
                    blocks,
                    farmer_reward_puzzle_hash=coinbase_puzzlehash,
                    pool_reward_puzzle_hash=coinbase_puzzlehash,
                    guarantee_transaction_block=True,
                    transaction_data=SpendBundle.aggregate(spend_bundles),
                    time_per_block=30,
                )

                b = blocks[-1]
                for coin in b.get_included_reward_coins():
                    if coin.puzzle_hash == coinbase_puzzlehash:
                        unspent_coins.append(coin)
                unspent_coins.extend(new_coins)

                if b.transactions_info:
                    fill_rate = b.transactions_info.cost / test_constants.MAX_BLOCK_COST_CLVM
                else:
                    fill_rate = 0

                end_time = time.monotonic()

                print(
                    f"included {i} spend bundles. fill_rate: {fill_rate*100:.1f}% "
                    f"new coins: {len(new_coins)} time: {end_time - start_time:0.2f}s"
                )

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
