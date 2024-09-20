from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import textwrap
from contextlib import closing
from pathlib import Path
from time import monotonic
from typing import Any, Dict, List, Optional

import zstd

from chia.util.config import load_config, lock_and_load_config, save_config
from chia.util.db_wrapper import get_host_parameter_limit
from chia.util.path import path_from_root


# if either the input database or output database file is specified, the
# configuration file will not be updated to use the new database. Only when using
# the currently configured db file, and writing to the default output file will
# the configuration file also be updated
def db_upgrade_func(
    root_path: Path,
    in_db_path: Optional[Path] = None,
    out_db_path: Optional[Path] = None,
    *,
    no_update_config: bool = False,
    force: bool = False,
) -> None:
    update_config: bool = in_db_path is None and out_db_path is None and not no_update_config

    config: Dict[str, Any]
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
        out_db_path.parent.mkdir(parents=True, exist_ok=True)

    _, _, free = shutil.disk_usage(out_db_path.parent)
    in_db_size = in_db_path.stat().st_size
    if free < in_db_size:
        no_free: bool = free < in_db_size * 0.6
        strength: str
        if no_free:
            strength = "probably not enough"
        else:
            strength = "very little"
        print(f"there is {strength} free space on the volume where the output database will be written:")
        print(f"   {out_db_path}")
        print(
            f"free space: {free / 1024 / 1024 / 1024:0.2f} GiB expected about "
            f"{in_db_size / 1024 / 1024 / 1024:0.2f} GiB"
        )
        if no_free and not force:
            print("to override this check and convert anyway, pass --force")
            return

    try:
        convert_v1_to_v2(in_db_path, out_db_path)

        if update_config:
            print("updating config.yaml")
            with lock_and_load_config(root_path, "config.yaml") as config:
                new_db_path = db_pattern.replace("_v1_", "_v2_")
                config["full_node"]["database_path"] = new_db_path
                print(f"database_path: {new_db_path}")
                save_config(root_path, "config.yaml", config)

    except RuntimeError as e:
        print(f"conversion failed with error: {e}.")
    except Exception as e:
        print(
            textwrap.dedent(
                f"""\
            conversion failed with error: {e}.
            The target v2 database is left in place (possibly in an incomplete state)
              {out_db_path}
            If the failure was caused by a full disk, ensure the volumes of your
            temporary- and target directory have sufficient free space."""
            )
        )
        if platform.system() == "Windows":
            temp_dir = None
            # this is where GetTempPath() looks
            # https://docs.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-gettemppatha
            if "TMP" in os.environ:
                temp_dir = os.environ["TMP"]
            elif "TEMP" in os.environ:
                temp_dir = os.environ["TEMP"]
            elif "USERPROFILE" in os.environ:
                temp_dir = os.environ["USERPROFILE"]
            if temp_dir is not None:
                print(f"your temporary directory may be {temp_dir}")
            temp_env = "TMP"
        else:
            temp_env = "SQLITE_TMPDIR"
        print(f'you can specify the "{temp_env}" environment variable to control the temporary directory to be used')

    print(f"\n\nLEAVING PREVIOUS DB FILE UNTOUCHED {in_db_path}\n")


def convert_v1_to_v2(in_path: Path, out_path: Path) -> None:
    BATCH_SIZE = 300_000
    if not in_path.exists():
        raise RuntimeError(f"Input file doesn't exist. {in_path}")
    if in_path == out_path:
        raise RuntimeError(f"Output file is the same as the input {in_path}")
    if out_path.exists():
        raise RuntimeError(f"Output file already exists. {out_path}")

    print(f"-- Opening file for reading: {in_path}")
    with sqlite3.connect(in_path) as conn:
        try:
            with closing(conn.execute("SELECT version FROM database_version LIMIT 1")) as cursor:
                row = cursor.fetchone()
            if row is not None and row[0] != 1:
                raise RuntimeError(f"Blockchain database already version {row[0]}. Won't convert")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("SELECT unhex('00')")
        except sqlite3.OperationalError:
            print("-- No built-in unhex(), falling back to bytes.fromhex()")
            conn.create_function("unhex", 1, bytes.fromhex)
        conn.create_function("zstd_compress", 1, zstd.compress)
        conn.execute("PRAGMA synchronous=off")
        temp_dir = tempfile.gettempdir()
        _, _, free = shutil.disk_usage(temp_dir)
        if free < 50 * 1024 * 1024 * 1024:
            print(f"-- Setting temp_store_directory to: {out_path.parent}")
            conn.execute(f"PRAGMA temp_store_directory = '{out_path.parent}'")
        print(f"-- Opening file for writing: {out_path}")
        conn.execute("ATTACH DATABASE ? AS out_db", (str(out_path),))
        conn.execute("PRAGMA out_db.journal_mode=off")
        conn.execute("PRAGMA out_db.synchronous=off")
        conn.execute("PRAGMA out_db.locking_mode=exclusive")
        conn.execute("PRAGMA out_db.cache_size=131072")
        print("-- Initializing v2 version")
        conn.execute("CREATE TABLE out_db.database_version(version int)")
        conn.execute("INSERT INTO out_db.database_version VALUES(?)", (2,))
        print("-- Initializing current_peak")
        conn.execute("CREATE TABLE out_db.current_peak(key int PRIMARY KEY, hash blob)")
        with closing(conn.execute("SELECT header_hash, height FROM block_records WHERE is_peak = 1 LIMIT 1")) as cursor:
            peak_row = cursor.fetchone()
        if peak_row is None:
            raise RuntimeError("v1 database does not have a peak block, there is no blockchain to convert")
        peak_hash, peak_height = peak_row
        print(f"-- Peak: {peak_hash} Height: {peak_height}")
        conn.execute("INSERT INTO out_db.current_peak VALUES(?, ?)", (0, bytes.fromhex(peak_hash)))
        conn.commit()
        print("-- DB v1 to v2 conversion started")
        print("-- [1/4] Converting full_blocks")
        conn.execute(
            """
            CREATE TABLE out_db.full_blocks(
                header_hash blob PRIMARY KEY,
                prev_hash blob,
                height bigint,
                sub_epoch_summary blob,
                is_fully_compactified tinyint,
                in_main_chain tinyint,
                block blob,
                block_record blob
            )
            """
        )
        conn.commit()
        parameter_limit = get_host_parameter_limit()
        start_time = monotonic()
        block_start_time = start_time
        rowids: List[int] = []
        small_batch_size = BATCH_SIZE <= parameter_limit
        small_chain = peak_height <= parameter_limit
        current_header_hash = peak_hash
        current_height = peak_height
        insertions_vs_batch = 0
        rate = 1.0
        while current_height >= 0:
            while len(rowids) < parameter_limit:
                if current_height < 0:
                    break
                with closing(
                    conn.execute(
                        "SELECT rowid, prev_hash FROM block_records WHERE header_hash = ? AND height = ? LIMIT 1",
                        (current_header_hash, current_height),
                    )
                ) as cursor:
                    row = cursor.fetchone()
                if row is None:
                    raise RuntimeError(f"rowid not found for {current_header_hash} at height {current_height}")
                rowid, prev_hash = row
                rowids.append(rowid)
                current_header_hash = prev_hash
                current_height -= 1
            conn.execute(
                f"""
                INSERT INTO out_db.full_blocks
                    SELECT
                        unhex(br.header_hash),
                        unhex(br.prev_hash),
                        br.height, br.sub_epoch_summary,
                        fb.is_fully_compactified,
                        1 AS in_main_chain,
                        zstd_compress(fb.block),
                        br.block
                    FROM block_records br
                    JOIN full_blocks fb ON br.header_hash = fb.header_hash
                    WHERE br.rowid IN ({','.join('?' * len(rowids))})
                """,
                rowids,
            )
            insertions_vs_batch += len(rowids)
            rowids = []
            if insertions_vs_batch >= BATCH_SIZE or small_batch_size or small_chain:
                conn.commit()
                end_time = monotonic()
                rate = BATCH_SIZE / (end_time - start_time)
                print(
                    f"\r{current_height:10d} {(peak_height - current_height) * 100 / peak_height:.3f}% "
                    f"{rate:0.1f} blocks/s ETA: {current_height // rate} s    ",
                    end="",
                )
                sys.stdout.flush()
                start_time = end_time
                insertions_vs_batch = 0
        end_time = monotonic()
        print(
            "\r-- [1/4] Converting full_blocks SUCCEEDED in "
            f"{end_time - block_start_time:.2f} seconds                             "
        )
        print("-- [1/4] Creating full_blocks height index")
        height_index_start_time = monotonic()
        conn.execute("CREATE INDEX out_db.height ON full_blocks(height)")
        conn.commit()
        end_time = monotonic()
        print(
            "\r-- [1/4] Creating full_blocks height index SUCCEEDED in "
            f"{end_time - height_index_start_time:.2f} seconds                             "
        )
        print("-- [1/4] Creating full_blocks is_fully_compactified index")
        ifc_index_start_time = monotonic()
        conn.execute(
            """
            CREATE INDEX out_db.is_fully_compactified
                ON full_blocks(is_fully_compactified, in_main_chain)
                WHERE in_main_chain=1
            """
        )
        conn.commit()
        end_time = monotonic()
        print(
            "\r-- [1/4] Creating full_blocks is_fully_compactified index SUCCEEDED in "
            f"{end_time - ifc_index_start_time:.2f} seconds                             "
        )
        print("-- [1/4] Creating full_blocks main_chain index")
        main_chain_index_start_time = monotonic()
        conn.execute(
            """
            CREATE INDEX out_db.main_chain
                ON full_blocks(height, in_main_chain)
                WHERE in_main_chain=1
            """
        )
        conn.commit()
        end_time = monotonic()
        print(
            "\r-- [1/4] Creating full_blocks main_chain index SUCCEEDED in "
            f"{end_time - main_chain_index_start_time:.2f} seconds                             "
        )
        print("-- [2/4] Converting sub_epoch_segments_v3")
        conn.execute(
            """
            CREATE TABLE out_db.sub_epoch_segments_v3(
                ses_block_hash blob PRIMARY KEY,
                challenge_segments blob
            )
            """
        )
        conn.commit()
        ses_start_time = monotonic()
        conn.execute(
            """
            INSERT INTO out_db.sub_epoch_segments_v3
                SELECT
                    unhex(ses_block_hash),
                    challenge_segments
                FROM sub_epoch_segments_v3
            """
        )
        conn.commit()
        end_time = monotonic()
        print(
            "\r-- [2/4] Converting sub_epoch_segments_v3 SUCCEEDED in "
            f"{end_time - ses_start_time:.2f} seconds                             "
        )
        print("-- [3/4] Converting hints")
        conn.execute("CREATE TABLE out_db.hints(coin_id blob, hint blob, UNIQUE (coin_id, hint))")
        conn.commit()
        start_time = monotonic()
        hint_start_time = start_time
        hints_count = 0
        rate = 1.0
        range_start = 1
        while True:
            with closing(
                conn.execute("SELECT id FROM hints WHERE id >= ? LIMIT ?", (range_start, parameter_limit))
            ) as cursor:
                rows = cursor.fetchall()
            if len(rows) == 0:
                break
            conn.execute(
                f"""
                INSERT OR IGNORE INTO out_db.hints
                    SELECT
                        coin_id,
                        hint
                    FROM hints
                    WHERE id IN ({','.join('?' * len(rows))})
                """,
                [id_tuple[0] for id_tuple in rows],
            )
            conn.commit()
            end_time = monotonic()
            rate = parameter_limit / (end_time - start_time)
            start_time = end_time
            hints_count += len(rows)
            print(f"\r{hints_count // 1000:10d}k hints {rate:0.1f} hints/s  ", end="")
            sys.stdout.flush()
            range_start += parameter_limit
        end_time = monotonic()
        print(
            "\r-- [3/4] Converting hints SUCCEEDED in "
            f"{end_time - hint_start_time:.2f} seconds                             "
        )
        print("-- [3/4] Creating hints hint_index index")
        hint_index_start_time = monotonic()
        conn.execute("CREATE INDEX out_db.hint_index on hints(hint)")
        conn.commit()
        end_time = monotonic()
        print(
            "\r-- [3/4] Creating hints hint_index index SUCCEEDED in "
            f"{end_time - hint_index_start_time:.2f} seconds                             "
        )
        print("-- [4/4] Converting coin_record")
        conn.execute(
            """
            CREATE TABLE out_db.coin_record(
                coin_name blob PRIMARY KEY,
                confirmed_index bigint,
                spent_index bigint,
                coinbase int,
                puzzle_hash blob,
                coin_parent blob,
                amount blob,
                timestamp bigint
            )
            """
        )
        conn.commit()
        start_time = monotonic()
        coin_start_time = start_time
        coins_count = 0
        rate = 1.0
        print("-- [4/4] Creating temp table (slow, patience)", end="\r")
        conn.execute(
            """
            CREATE TABLE temp.coin_record AS
            SELECT
                unhex(coin_name),
                confirmed_index,
                CASE WHEN spent_index <= ? THEN spent_index ELSE 0 END AS spent_index,
                coinbase,
                unhex(puzzle_hash),
                unhex(coin_parent),
                amount,
                timestamp
            FROM coin_record
            WHERE confirmed_index <= ?
            ORDER BY unhex(coin_name)
            """,
            (peak_height, peak_height),
        )
        with closing(conn.execute("SELECT * FROM temp.coin_record")) as cursor:
            while True:
                rows = cursor.fetchmany(BATCH_SIZE)
                if len(rows) == 0:
                    break
                conn.executemany("INSERT INTO out_db.coin_record VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
                conn.commit()
                end_time = monotonic()
                rate = len(rows) / (end_time - start_time)
                start_time = end_time
                coins_count += len(rows)
                print(f"\r{coins_count // 1000:10d}k coins {rate:0.1f} coins/s               ", end="")
                sys.stdout.flush()
        end_time = monotonic()
        print(
            "\r-- [4/4] Converting coin_record SUCCEEDED in "
            f"{end_time - coin_start_time:.2f} seconds                             "
        )
        print("-- [4/4] Creating coin_record coin_confirmed_index index")
        coin_confirmed_index_start_time = monotonic()
        conn.execute("CREATE INDEX out_db.coin_confirmed_index ON coin_record(confirmed_index)")
        conn.commit()
        end_time = monotonic()
        print(
            "\r-- [4/4] Creating coin_record coin_confirmed_index index SUCCEEDED in "
            f"{end_time - coin_confirmed_index_start_time:.2f} seconds                             "
        )
        print("-- [4/4] Creating coin_record coin_spent_index index")
        coin_spent_index_start_time = monotonic()
        conn.execute("CREATE INDEX out_db.coin_spent_index ON coin_record(spent_index)")
        conn.commit()
        end_time = monotonic()
        print(
            "\r-- [4/4] Creating coin_record coin_spent_index index SUCCEEDED in "
            f"{end_time - coin_spent_index_start_time:.2f} seconds                             "
        )
        print("-- [4/4] Creating coin_record coin_puzzle_hash index")
        coin_puzzle_hash_index_start_time = monotonic()
        conn.execute("CREATE INDEX out_db.coin_puzzle_hash ON coin_record(puzzle_hash)")
        conn.commit()
        end_time = monotonic()
        print(
            "\r-- [4/4] Creating coin_record coin_puzzle_hash index SUCCEEDED in "
            f"{end_time - coin_puzzle_hash_index_start_time:.2f} seconds                             "
        )
        print("-- [4/4] Creating coin_record coin_parent_index index")
        coin_parent_index_start_time = monotonic()
        conn.execute("CREATE INDEX out_db.coin_parent_index ON coin_record(coin_parent)")
        conn.commit()
        end_time = monotonic()
        print(
            "\r-- [4/4] Creating coin_record coin_parent_index index SUCCEEDED in "
            f"{end_time - coin_parent_index_start_time:.2f} seconds                             "
        )
        conn.execute("DETACH DATABASE out_db")
