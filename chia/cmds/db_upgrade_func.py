from typing import Dict, Optional
from pathlib import Path
import sys
from time import time

import asyncio
import zstd
from chia.util import dialect_utils

from chia.util.config import load_config, save_config
from chia.util.db_factory import get_database_connection
from chia.util.path import mkdir, path_from_root
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.types.blockchain_format.sized_bytes import bytes32


# if either the input database or output database file is specified, the
# configuration file will not be updated to use the new database. Only when using
# the currently configured db file, and writing to the default output file will
# the configuration file also be updated
def db_upgrade_func(
    root_path: Path,
    in_db_path: Optional[Path] = None,
    out_db_path: Optional[Path] = None,
    no_update_config: bool = False,
):

    update_config: bool = in_db_path is None and out_db_path is None and not no_update_config

    config: Dict
    selected_network: str
    db_pattern: str
    if in_db_path is None or out_db_path is None:
        config = load_config(root_path, "config.yaml")["full_node"]
        selected_network = config["selected_network"]
        db_pattern = config["database_path"]

    db_path_replaced: str
    if in_db_path is None:
        db_path_replaced = db_pattern.replace("CHALLENGE", selected_network)
        in_db_path = path_from_root(root_path, db_path_replaced)

    if out_db_path is None:
        db_path_replaced = db_pattern.replace("CHALLENGE", selected_network).replace("_v1_", "_v2_")
        out_db_path = path_from_root(root_path, db_path_replaced)
        mkdir(out_db_path.parent)

    asyncio.run(convert_v1_to_v2(in_db_path, out_db_path))

    if update_config:
        print("updating config.yaml")
        config = load_config(root_path, "config.yaml")
        new_db_path = db_pattern.replace("_v1_", "_v2_")
        config["full_node"]["database_path"] = new_db_path
        print(f"database_path: {new_db_path}")
        save_config(root_path, "config.yaml", config)

    print(f"\n\nLEAVING PREVIOUS DB FILE UNTOUCHED {in_db_path}\n")


BLOCK_COMMIT_RATE = 10000
SES_COMMIT_RATE = 2000
HINT_COMMIT_RATE = 2000
COIN_COMMIT_RATE = 30000


async def convert_v1_to_v2(in_path: Path, out_path: Path) -> None:
    from chia.util.db_wrapper import DBWrapper

    if out_path.exists():
        print(f"output file already exists. {out_path}")
        raise RuntimeError("already exists")

    print(f"opening file for reading: {in_path}")
    async with await get_database_connection(in_path) as in_db:
        try:
            row = await in_db.fetch_one("SELECT * from database_version")

            if row is not None and row[0] != 1:
                print(f"blockchain database already version {row[0]}\nDone")
                raise RuntimeError("already v2")
        except:
            pass

        store_v1 = await BlockStore.create(DBWrapper(in_db, db_version=1))

        print(f"opening file for writing: {out_path}")
        async with await get_database_connection(out_path) as out_db:
            async with out_db.connection() as connection:
                if out_db.url.dialect == 'sqlite':
                        await out_db.execute("pragma journal_mode=OFF")
                        await out_db.execute("pragma synchronous=OFF")
                        await out_db.execute("pragma cache_size=131072")
                        await out_db.execute("pragma locking_mode=exclusive")
                async with connection.transaction():
                    print("initializing v2 version")
                    await out_db.execute("CREATE TABLE database_version(version int)")
                    await out_db.execute("INSERT INTO database_version VALUES(:version)", {"version": 2})

                    print("initializing v2 block store")
                    await out_db.execute(
                        "CREATE TABLE full_blocks("
                        f"header_hash {dialect_utils.data_type('blob-as-index', out_db.url.dialect)} PRIMARY KEY,"
                        f"prev_hash {dialect_utils.data_type('blob', out_db.url.dialect)},"
                        "height bigint,"
                        f"sub_epoch_summary {dialect_utils.data_type('blob', out_db.url.dialect)},"
                        f"is_fully_compactified {dialect_utils.data_type('tinyint', out_db.url.dialect)},"
                        f"in_main_chain {dialect_utils.data_type('tinyint', out_db.url.dialect)},"
                        f"block {dialect_utils.data_type('blob', out_db.url.dialect)},"
                        f"block_record {dialect_utils.data_type('blob', out_db.url.dialect)})"
                    )
                    await out_db.execute(
                        f"CREATE TABLE sub_epoch_segments_v3(ses_block_hash {dialect_utils.data_type('blob-as-index', out_db.url.dialect)} PRIMARY KEY, challenge_segments {dialect_utils.data_type('blob', out_db.url.dialect)})"
                    )
                    await out_db.execute(f"CREATE TABLE current_peak(key int PRIMARY KEY, hash {dialect_utils.data_type('blob', out_db.url.dialect)})")

                    peak_hash, peak_height = await store_v1.get_peak()
                    print(f"peak: {peak_hash.hex()} height: {peak_height}")

                    await out_db.execute("INSERT INTO current_peak(key, hash) VALUES(:key, :hash)", {"key": 0, "hash":  peak_hash})

            print("[1/5] converting full_blocks")
            height = peak_height + 1
            hh = peak_hash

            commit_in = BLOCK_COMMIT_RATE
            rate = 1.0
            start_time = time()
            block_start_time = start_time
            block_values = []

            block_record_rows = await in_db.fetch_all(
                "SELECT header_hash, prev_hash, block, sub_epoch_summary FROM block_records ORDER BY height DESC"
            )
            full_block_rows_map = {}
            for full_block_row in (await in_db.fetch_all("SELECT header_hash, height, is_fully_compactified, block FROM full_blocks ORDER BY height DESC")):
                full_block_rows_map[bytes.fromhex(full_block_row[0])] = full_block_row

            for block_record_row in block_record_rows:

                header_hash = bytes.fromhex(block_record_row[0])
                if header_hash != hh:
                    continue


                if hh in full_block_rows_map:
                    target_full_block_row = full_block_rows_map[hh]
                else:
                    print(f"ERROR: could not find block {hh.hex()}")
                    raise RuntimeError(f"block {hh.hex()} not found")


                assert target_full_block_row[1] == height - 1
                height = target_full_block_row[1]
                is_fully_compactified = target_full_block_row[2]
                block_bytes = target_full_block_row[3]

                prev_hash = bytes.fromhex(block_record_row[1])
                block_record = block_record_row[2]
                ses = block_record_row[3]

                block_values.append(
                    {
                        "header_hash": hh,
                        "prev_hash": prev_hash,
                        "height": int(height),
                        "sub_epoch_summary": ses,
                        "is_fully_compactified": int(is_fully_compactified),
                        "in_main_chain": 1,  # in_main_chain
                        "block": zstd.compress(block_bytes),
                        "block_record": block_record,
                    }
                )
                hh = prev_hash
                if (height % 1000) == 0:
                    print(
                        f"\r{height: 10d} {(peak_height-height)*100/peak_height:.2f}% "
                        f"{rate:0.1f} blocks/s ETA: {height//rate} s    ",
                        end="",
                    )
                    sys.stdout.flush()
                commit_in -= 1
                if commit_in == 0:
                    commit_in = BLOCK_COMMIT_RATE
                    await out_db.execute_many(
                        "INSERT OR REPLACE INTO full_blocks(header_hash, prev_hash, height, sub_epoch_summary, is_fully_compactified, in_main_chain, block, block_record) VALUES(:header_hash, :prev_hash, :height, :sub_epoch_summary, :is_fully_compactified, :in_main_chain, :block, :block_record)", block_values
                    )
                    block_values = []
                    end_time = time()
                    rate = BLOCK_COMMIT_RATE / (end_time - start_time)
                    start_time = end_time

            await out_db.execute_many(
                "INSERT OR REPLACE INTO full_blocks(header_hash, prev_hash, height, sub_epoch_summary, is_fully_compactified, in_main_chain, block, block_record) VALUES(:header_hash, :prev_hash, :height, :sub_epoch_summary, :is_fully_compactified, :in_main_chain, :block, :block_record)", block_values
            )
            end_time = time()
            print(f"\r      {end_time - block_start_time:.2f} seconds                             ")

            print("[2/5] converting sub_epoch_segments_v3")

            commit_in = SES_COMMIT_RATE
            ses_values = []
            ses_start_time = time()
            rows = await in_db.fetch_all("SELECT ses_block_hash, challenge_segments FROM sub_epoch_segments_v3")
            count = 0
            for row in rows:
                block_hash = bytes32.fromhex(row[0])
                ses = row[1]
                ses_values.append({"ses_block_hash": block_hash, "challenge_segments":  ses})
                count += 1
                if (count % 100) == 0:
                    print(f"\r{count:10d}  ", end="")
                    sys.stdout.flush()

                commit_in -= 1
                if commit_in == 0:
                    commit_in = SES_COMMIT_RATE
                    await out_db.execute_many("INSERT INTO sub_epoch_segments_v3(ses_block_hash, challenge_segments) VALUES (:ses_block_hash, :challenge_segments)", ses_values)
                    ses_values = []

            await out_db.execute_many("INSERT INTO sub_epoch_segments_v3(ses_block_hash, challenge_segments) VALUES (:ses_block_hash, :challenge_segments)", ses_values)

            end_time = time()
            print(f"\r      {end_time - ses_start_time:.2f} seconds                             ")

            print("[3/5] converting hint_store")

            commit_in = HINT_COMMIT_RATE
            hint_start_time = time()
            hint_values = []
            await out_db.execute(f"CREATE TABLE hints(coin_id {dialect_utils.data_type('blob-as-index', out_db.url.dialect)}, hint {dialect_utils.data_type('blob-as-index', out_db.url.dialect)}, UNIQUE (coin_id, hint))")
            rows = await in_db.fetch_all("SELECT coin_id, hint FROM hints")
            count = 0
            for row in rows:
                hint_values.append({"coin_id": row[0], "hint":  row[1]})
                commit_in -= 1
                if commit_in == 0:
                    commit_in = HINT_COMMIT_RATE
                    if len(hint_values) > 0:
                        await out_db.execute_many(
                            dialect_utils.insert_or_ignore_query('hints', ['coin_id'], hint_values[0].keys(), out_db.url.dialect),
                            hint_values
                        )
                    hint_values = []

            await out_db.execute_many(dialect_utils.insert_or_ignore_query('hints', ['coin_id'], hint_values[0].keys(), out_db.url.dialect), hint_values)

            end_time = time()
            print(f"\r      {end_time - hint_start_time:.2f} seconds                             ")

            print("[4/5] converting coin_store")
            await out_db.execute(
                "CREATE TABLE coin_record("
                f"coin_name {dialect_utils.data_type('blob-as-index', out_db.url.dialect)} PRIMARY KEY,"
                " confirmed_index bigint,"
                " spent_index bigint,"  # if this is zero, it means the coin has not been spent
                " coinbase int,"
                f" puzzle_hash {dialect_utils.data_type('blob', out_db.url.dialect)},"
                f" coin_parent {dialect_utils.data_type('blob', out_db.url.dialect)},"
                f" amount {dialect_utils.data_type('blob', out_db.url.dialect)},"  # we use a blob of 8 bytes to store uint64
                " timestamp bigint)"
            )

            commit_in = COIN_COMMIT_RATE
            rate = 1.0
            start_time = time()
            coin_values = []
            coin_start_time = start_time
            rows = await in_db.fetch_all(
                "SELECT coin_name, confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount, timestamp "
                "FROM coin_record WHERE confirmed_index <= :peak_height",
                {"peak_height": int(peak_height)},
            )
            count = 0
            for row in rows:
                spent_index = row[2]

                # in order to convert a consistent snapshot of the
                # blockchain state, any coin that was spent *after* our
                # cutoff must be converted into an unspent coin
                if spent_index > peak_height:
                    spent_index = 0

                coin_values.append(
                    {
                        "coin_name": bytes.fromhex(row[0]),
                        "confirmed_index": int(row[1]),
                        "spent_index": int(spent_index),
                        "coinbase": int(row[3]),
                        "puzzle_hash": bytes.fromhex(row[4]),
                        "coin_parent": bytes.fromhex(row[5]),
                        "amount": row[6],
                        "timestamp": int(row[7]),
                    }
                )
                count += 1
                if (count % 2000) == 0:
                    print(f"\r{count//1000:10d}k coins {rate:0.1f} coins/s  ", end="")
                    sys.stdout.flush()
                commit_in -= 1
                if commit_in == 0:
                    commit_in = COIN_COMMIT_RATE
                    await out_db.execute_many(
                        (
                            "INSERT INTO coin_record(coin_name, confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount, timestamp) "
                            "VALUES(:coin_name, :confirmed_index, :spent_index, :coinbase, :puzzle_hash, :coin_parent, :amount, :timestamp)"
                        ),
                        coin_values
                    )
                    coin_values = []
                    end_time = time()
                    rate = COIN_COMMIT_RATE / (end_time - start_time)
                    start_time = end_time

            await out_db.execute_many(
                (
                    "INSERT INTO coin_record(coin_name, confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount, timestamp) "
                    "VALUES(:coin_name, :confirmed_index, :spent_index, :coinbase, :puzzle_hash, :coin_parent, :amount, :timestamp)"
                ),
                coin_values
            )
            end_time = time()
            print(f"\r      {end_time - coin_start_time:.2f} seconds                             ")

            print("[5/5] build indices")
            index_start_time = time()
            print("      block store")
            await BlockStore.create(DBWrapper(out_db, db_version=2))
            print("      coin store")
            await CoinStore.create(DBWrapper(out_db, db_version=2))
            print("      hint store")
            await HintStore.create(DBWrapper(out_db, db_version=2))
            end_time = time()
            print(f"\r      {end_time - index_start_time:.2f} seconds                             ")
