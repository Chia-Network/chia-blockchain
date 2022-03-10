from typing import Dict, Optional
from pathlib import Path
import sys
from time import time

from chia.util.config import load_config, save_config, get_config_lock
from chia.util.path import mkdir, path_from_root
from chia.util.ints import uint32
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

    convert_v1_to_v2(in_db_path, out_db_path)

    if update_config:
        print("updating config.yaml")
        with get_config_lock(root_path, "config.yaml"):
            config = load_config(root_path, "config.yaml", acquire_lock=False)
            new_db_path = db_pattern.replace("_v1_", "_v2_")
            config["full_node"]["database_path"] = new_db_path
            print(f"database_path: {new_db_path}")
            save_config(root_path, "config.yaml", config)

    print(f"\n\nLEAVING PREVIOUS DB FILE UNTOUCHED {in_db_path}\n")


BLOCK_COMMIT_RATE = 10000
SES_COMMIT_RATE = 2000
HINT_COMMIT_RATE = 2000
COIN_COMMIT_RATE = 30000


def convert_v1_to_v2(in_path: Path, out_path: Path) -> None:
    import sqlite3
    import zstd

    from contextlib import closing

    if not in_path.exists():
        print(f"input file doesn't exist. {in_path}")
        raise RuntimeError(f"can't find {in_path}")

    if in_path == out_path:
        print(f"output file is the same as the input {in_path}")
        raise RuntimeError("invalid conversion files")

    if out_path.exists():
        print(f"output file already exists. {out_path}")
        raise RuntimeError("already exists")

    print(f"opening file for reading: {in_path}")
    with closing(sqlite3.connect(in_path)) as in_db:
        try:
            with closing(in_db.execute("SELECT * from database_version")) as cursor:
                row = cursor.fetchone()
                if row is not None and row[0] != 1:
                    print(f"blockchain database already version {row[0]}\nDone")
                    raise RuntimeError("already v2")
        except sqlite3.OperationalError:
            pass

        print(f"opening file for writing: {out_path}")
        with closing(sqlite3.connect(out_path)) as out_db:
            out_db.execute("pragma journal_mode=OFF")
            out_db.execute("pragma synchronous=OFF")
            out_db.execute("pragma cache_size=131072")
            out_db.execute("pragma locking_mode=exclusive")

            print("initializing v2 version")
            out_db.execute("CREATE TABLE database_version(version int)")
            out_db.execute("INSERT INTO database_version VALUES(?)", (2,))

            print("initializing v2 block store")
            out_db.execute(
                "CREATE TABLE full_blocks("
                "header_hash blob PRIMARY KEY,"
                "prev_hash blob,"
                "height bigint,"
                "sub_epoch_summary blob,"
                "is_fully_compactified tinyint,"
                "in_main_chain tinyint,"
                "block blob,"
                "block_record blob)"
            )
            out_db.execute(
                "CREATE TABLE sub_epoch_segments_v3(" "ses_block_hash blob PRIMARY KEY," "challenge_segments blob)"
            )
            out_db.execute("CREATE TABLE current_peak(key int PRIMARY KEY, hash blob)")

            with closing(in_db.execute("SELECT header_hash, height from block_records WHERE is_peak = 1")) as cursor:
                peak_row = cursor.fetchone()
                if peak_row is None:
                    print("v1 database does not have a peak block, there is no blockchain to convert")
                    raise RuntimeError("no blockchain")
            peak_hash = bytes32(bytes.fromhex(peak_row[0]))
            peak_height = uint32(peak_row[1])
            print(f"peak: {peak_hash.hex()} height: {peak_height}")

            out_db.execute("INSERT INTO current_peak VALUES(?, ?)", (0, peak_hash))
            out_db.commit()

            print("[1/5] converting full_blocks")
            height = peak_height + 1
            hh = peak_hash

            commit_in = BLOCK_COMMIT_RATE
            rate = 1.0
            start_time = time()
            block_start_time = start_time
            block_values = []

            with closing(
                in_db.execute(
                    "SELECT header_hash, prev_hash, block, sub_epoch_summary FROM block_records ORDER BY height DESC"
                )
            ) as cursor:
                with closing(
                    in_db.execute(
                        "SELECT header_hash, height, is_fully_compactified, block FROM full_blocks ORDER BY height DESC"
                    )
                ) as cursor_2:

                    out_db.execute("begin transaction")
                    for row in cursor:

                        header_hash = bytes.fromhex(row[0])
                        if header_hash != hh:
                            continue

                        # progress cursor_2 until we find the header hash
                        while True:
                            row_2 = cursor_2.fetchone()
                            if row_2 is None:
                                print(f"ERROR: could not find block {hh.hex()}")
                                raise RuntimeError(f"block {hh.hex()} not found")
                            if bytes.fromhex(row_2[0]) == hh:
                                break

                        assert row_2[1] == height - 1
                        height = row_2[1]
                        is_fully_compactified = row_2[2]
                        block_bytes = row_2[3]

                        prev_hash = bytes32.fromhex(row[1])
                        block_record = row[2]
                        ses = row[3]

                        block_values.append(
                            (
                                hh,
                                prev_hash,
                                height,
                                ses,
                                is_fully_compactified,
                                1,  # in_main_chain
                                zstd.compress(block_bytes),
                                block_record,
                            )
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
                            out_db.executemany(
                                "INSERT OR REPLACE INTO full_blocks VALUES(?, ?, ?, ?, ?, ?, ?, ?)", block_values
                            )
                            out_db.commit()
                            out_db.execute("begin transaction")
                            block_values = []
                            end_time = time()
                            rate = BLOCK_COMMIT_RATE / (end_time - start_time)
                            start_time = end_time

            out_db.executemany("INSERT OR REPLACE INTO full_blocks VALUES(?, ?, ?, ?, ?, ?, ?, ?)", block_values)
            out_db.commit()
            end_time = time()
            print(f"\r      {end_time - block_start_time:.2f} seconds                             ")

            print("[2/5] converting sub_epoch_segments_v3")

            commit_in = SES_COMMIT_RATE
            ses_values = []
            ses_start_time = time()
            with closing(
                in_db.execute("SELECT ses_block_hash, challenge_segments FROM sub_epoch_segments_v3")
            ) as cursor:
                count = 0
                out_db.execute("begin transaction")
                for row in cursor:
                    block_hash = bytes32.fromhex(row[0])
                    ses = row[1]
                    ses_values.append((block_hash, ses))
                    count += 1
                    if (count % 100) == 0:
                        print(f"\r{count:10d}  ", end="")
                        sys.stdout.flush()

                    commit_in -= 1
                    if commit_in == 0:
                        commit_in = SES_COMMIT_RATE
                        out_db.executemany("INSERT INTO sub_epoch_segments_v3 VALUES (?, ?)", ses_values)
                        out_db.commit()
                        out_db.execute("begin transaction")
                        ses_values = []

            out_db.executemany("INSERT INTO sub_epoch_segments_v3 VALUES (?, ?)", ses_values)
            out_db.commit()

            end_time = time()
            print(f"\r      {end_time - ses_start_time:.2f} seconds                             ")

            print("[3/5] converting hint_store")

            commit_in = HINT_COMMIT_RATE
            hint_start_time = time()
            hint_values = []
            out_db.execute("CREATE TABLE hints(coin_id blob, hint blob, UNIQUE (coin_id, hint))")
            out_db.commit()
            try:
                with closing(in_db.execute("SELECT coin_id, hint FROM hints")) as cursor:
                    count = 0
                    out_db.execute("begin transaction")
                    for row in cursor:
                        hint_values.append((row[0], row[1]))
                        commit_in -= 1
                        if commit_in == 0:
                            commit_in = HINT_COMMIT_RATE
                            out_db.executemany("INSERT OR IGNORE INTO hints VALUES(?, ?)", hint_values)
                            out_db.commit()
                            out_db.execute("begin transaction")
                            hint_values = []
            except sqlite3.OperationalError:
                print("      no hints table, skipping")

            out_db.executemany("INSERT OR IGNORE INTO hints VALUES (?, ?)", hint_values)
            out_db.commit()

            end_time = time()
            print(f"\r      {end_time - hint_start_time:.2f} seconds                             ")

            print("[4/5] converting coin_store")
            out_db.execute(
                "CREATE TABLE coin_record("
                "coin_name blob PRIMARY KEY,"
                " confirmed_index bigint,"
                " spent_index bigint,"  # if this is zero, it means the coin has not been spent
                " coinbase int,"
                " puzzle_hash blob,"
                " coin_parent blob,"
                " amount blob,"  # we use a blob of 8 bytes to store uint64
                " timestamp bigint)"
            )
            out_db.commit()

            commit_in = COIN_COMMIT_RATE
            rate = 1.0
            start_time = time()
            coin_values = []
            coin_start_time = start_time
            with closing(
                in_db.execute(
                    "SELECT coin_name, confirmed_index, spent_index, coinbase, "
                    "puzzle_hash, coin_parent, amount, timestamp "
                    "FROM coin_record WHERE confirmed_index <= ?",
                    (peak_height,),
                )
            ) as cursor:
                count = 0
                out_db.execute("begin transaction")
                for row in cursor:
                    spent_index = row[2]

                    # in order to convert a consistent snapshot of the
                    # blockchain state, any coin that was spent *after* our
                    # cutoff must be converted into an unspent coin
                    if spent_index > peak_height:
                        spent_index = 0

                    coin_values.append(
                        (
                            bytes.fromhex(row[0]),
                            row[1],
                            spent_index,
                            row[3],
                            bytes.fromhex(row[4]),
                            bytes.fromhex(row[5]),
                            row[6],
                            row[7],
                        )
                    )
                    count += 1
                    if (count % 2000) == 0:
                        print(f"\r{count//1000:10d}k coins {rate:0.1f} coins/s  ", end="")
                        sys.stdout.flush()
                    commit_in -= 1
                    if commit_in == 0:
                        commit_in = COIN_COMMIT_RATE
                        out_db.executemany("INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)", coin_values)
                        out_db.commit()
                        out_db.execute("begin transaction")
                        coin_values = []
                        end_time = time()
                        rate = COIN_COMMIT_RATE / (end_time - start_time)
                        start_time = end_time

            out_db.executemany("INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)", coin_values)
            out_db.commit()
            end_time = time()
            print(f"\r      {end_time - coin_start_time:.2f} seconds                             ")

            print("[5/5] build indices")
            index_start_time = time()
            print("      block store")
            out_db.execute("CREATE INDEX height on full_blocks(height)")
            out_db.execute(
                "CREATE INDEX is_fully_compactified ON"
                " full_blocks(is_fully_compactified, in_main_chain) WHERE in_main_chain=1"
            )
            out_db.execute("CREATE INDEX main_chain ON full_blocks(height, in_main_chain) WHERE in_main_chain=1")
            out_db.commit()
            print("      coin store")

            out_db.execute("CREATE INDEX IF NOT EXISTS coin_confirmed_index on coin_record(confirmed_index)")
            out_db.execute("CREATE INDEX IF NOT EXISTS coin_spent_index on coin_record(spent_index)")
            out_db.execute("CREATE INDEX IF NOT EXISTS coin_puzzle_hash on coin_record(puzzle_hash)")
            out_db.execute("CREATE INDEX IF NOT EXISTS coin_parent_index on coin_record(coin_parent)")
            out_db.commit()
            print("      hint store")

            out_db.execute("CREATE TABLE IF NOT EXISTS hints(coin_id blob, hint blob, UNIQUE (coin_id, hint))")
            out_db.commit()
            end_time = time()
            print(f"\r      {end_time - index_start_time:.2f} seconds                             ")
