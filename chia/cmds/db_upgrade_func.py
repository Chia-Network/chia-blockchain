from typing import Dict, Optional
from pathlib import Path
import sys
from os import remove
from time import time

# from psutil import virtual_memory, disk_usage

# replaced aiosqlite by sqlite3 due to better performance and no aio is needed
import sqlite3
import zstd

from chia.util.config import load_config, save_config
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

    out_path_string: str
    if out_db_path is None:
        db_path_replaced = db_pattern.replace("CHALLENGE", selected_network).replace("_v1_", "_v2_")
        out_db_path = path_from_root(root_path, db_path_replaced)
        mkdir(out_db_path.parent)
        out_path_string = db_path_replaced
        out_path_string = str(out_db_path)

    convert_v1_to_v2(in_db_path, out_db_path, out_path_string)

    if update_config:
        print("updating config.yaml")
        config = load_config(root_path, "config.yaml")
        new_db_path = db_pattern.replace("_v1_", "_v2_")
        config["full_node"]["database_path"] = new_db_path
        print(f"database_path: {new_db_path}")
        save_config(root_path, "config.yaml", config)

    print(f"\n\nLEAVING PREVIOUS DB FILE UNTOUCHED {in_db_path}\n")


# Using these row sizes should keep memory usage <= 4G
# Probably half these settings for systems with 4G memory only
BLOCK_COMMIT_RATE = 80000
COIN_COMMIT_RATE = 300000
SES_COMMIT_RATE = 50
HINT_COMMIT_RATE = 150000
# These parameter were used to decouple pragma shring_memory from commit
# commented out as shrink memory is not needed any more
# BLOCK_SHRINK_RATE = BLOCK_COMMIT_RATE * 1.5
# COIN_SHRINK_RATE = COIN_COMMIT_RATE * 1.2
# SES_SHRINK_RATE = SES_COMMIT_RATE * 1.2
# HINT_SHRINK_RATE = HINT_COMMIT_RATE * 1.5


def connect_to_db(open_in_path: Path, attach_out_path: str):
    db = sqlite3.connect(open_in_path)
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * from database_version")
        row = cursor.fetchone()
        if row is not None and row[0] == 2:
            print(f"blockchain database already version {row[0]}\nDone")
            raise RuntimeError("already v2")
    except sqlite3.OperationalError:
        pass
    finally:
        cursor.close()

    db.execute("PRAGMA JOURNAL_MODE=off")
    db.execute("PRAGMA SYNCHRONOUS=off")
    # Threads is only used for temp table or indexes didn't bring any improvement
    # db.execute("PRAGMA threads=4")
    db.execute("PRAGMA mmap_size=2147418112")
    db.execute("PRAGMA cache_spill=false")

    # CHANGE PAGE_SIZE
    # comment this block if you don't want to change page size
    # if not path.exists(attach_out_path):
    #    init_pagesize = sqlite3.connect(attach_out_path)
    #    init_pagesize.execute("PRAGMA PAGE_SIZE=8192")
    #    init_pagesize.execute("VACUUM")
    #    init_pagesize.close()

    db.execute("ATTACH DATABASE ? AS v2db", (attach_out_path,))
    # Set parameter for attached database only
    db.execute("pragma v2db.journal_mode=OFF")
    db.execute("pragma v2db.synchronous=OFF")
    db.execute("pragma v2db.locking_mode=exclusive")

    return db


def convert_v1_to_v2(in_path: Path, out_path: Path, out_path_string: str) -> None:

    if out_path.exists():
        print(f"output file already exists. {out_path}")
        raise RuntimeError("already exists")

    print(f"\n\nopening file for reading: {in_path}")
    in_db = connect_to_db(in_path, out_path_string)

    #  The update is split into the following stages
    #  0. Initialzhe new target v2 database
    #     a) create database_version table and save version
    #     b) create current_peak table and save current peak
    #     c) create empty target v2 tables
    #        decided to don't source these statements from block_store.py, ... to not load LRU caches or such
    #  1. Convert full_blocks to v2 and load data to target v2 tables
    #   2. Create full_blocks indexes on v2 tables
    #    decided to create indexes right after table data migration to get possible use of data in fs cache
    #  3. Convert coin_store tables to temp sqlite db file
    #     decided to use this approach and disconnect/recoonect sqlite sessions to get use of mmap
    #  4. convert sub_epoch tables to temp sqlite db file
    #  5. Migrate coin_store temp data to target v2 sqlite file
    #  6. Create Indexes on coin_store tables
    #  7. Migrate sub_epoch tables to target v2 sqlite file
    #  8. Placeholder (was used to create unique index on sub_epoch table to test table without Pk)
    #     Questions:
    #     -) is it possible to move this table to a separate sqlite db file?
    #        This table would imo benefit from 64k page size, due to the big size of its rows (on avg 600k).
    #        Right now the data is scattered over the whole sqlite file.
    #     -) on hints table, the PK was removed and a workaround using 'ON CONFLICT DO NOTHING' was introduced
    #        I saw that data is inserted every about 9s with replace, so the hints approach is probably also valid here?
    #  9. Convert and migrate hints table to target v2 sqlite file
    # 10. Create indexes on hints table
    # Finally update the database version to 2
    #
    # Possible improvements:
    # -) check if target device for default temp_store is big enough or maybe better, let user choose temp_store_directory
    #    HOW TO DECIDE: 
    #      1. better SSD > HDD
    #      2. if applicable, choose different device than the db device
    #      3. free space needed: sum of coin_record + sub_epoch_segments_v3:
    #         select sum(pgsize)/1024/1024 MB from dbstat where name in ('coin_record','sub_epoch_segments_v3');
    # -) check if db device has enough free space: 
    #         select sum(pgsize)/1024/1024 MB from dbstat;
    # -) get available memory and choose batch commit sizes accordingly

    print("\n[0/10] initializing v2 database with current_peak")

    # CURRENT_PEAK START
    # The table current_peak would probably benefit from a without rowid implementation
    # CREATE TABLE current_peak(hash blob PRIMARY KEY) WITHOUT ROWID;
    #
    # Setting new peak would be as easy as: UPDATE current_peak set hash='Iamthenewpeakshash';
    # Access would be directly by rowid, although the impact would be minimal on only occasional accesses

    in_db.execute("BEGIN TRANSACTION")

    in_db.execute("CREATE TABLE v2db.database_version(version int)")
    in_db.execute("INSERT INTO v2db.database_version VALUES(?)", (2,))
    in_db.execute("CREATE TABLE v2db.current_peak(key int PRIMARY KEY, hash blob)")

    ####
    # part is taken from get_peak function (block_store.py)
    ####
    cursor_peak = in_db.cursor()
    cursor_peak.execute("SELECT header_hash, height from main.block_records WHERE is_peak = 1")
    peak_row = cursor_peak.fetchone()
    if peak_row is None:
        return None
    peak_hash = bytes32(bytes.fromhex(peak_row[0]))
    peak_height = uint32(peak_row[1])
    cursor_peak.close()
    ####

    print(f"\tv2 database file: {out_path}")
    print(f"\tpeak: {peak_hash.hex()}\n\theight: {peak_height}")

    in_db.execute("INSERT OR REPLACE INTO v2db.current_peak VALUES(?, ?)", (0, peak_hash))
    in_db.commit()

    # CURRENT_PEAK END

    print("\tcreating v2 database tables")

    in_db.execute(
        "CREATE TABLE IF NOT EXISTS v2db.full_blocks("
        "header_hash blob PRIMARY KEY,"
        "prev_hash blob,"
        "height bigint,"
        "sub_epoch_summary blob,"
        "is_fully_compactified tinyint,"
        "in_main_chain tinyint,"
        "block blob,"
        "block_record blob"
        ")"
    )

    in_db.execute(
        "CREATE TABLE IF NOT EXISTS v2db.sub_epoch_segments_v3("
        "ses_block_hash blob PRIMARY KEY,"
        "challenge_segments blob)"
    )

    in_db.execute(
        "CREATE TABLE IF NOT EXISTS v2db.coin_record("
        "coin_name blob PRIMARY KEY,"
        "confirmed_index bigint,"
        "spent_index bigint,"  # if this is zero, it means the coin has not been spent
        "coinbase int,"
        "puzzle_hash blob,"
        "coin_parent blob,"
        "amount blob,"  # we use a blob of 8 bytes to store uint64
        "timestamp bigint)"
    )

    in_db.execute("CREATE TABLE IF NOT EXISTS v2db.hints(coin_id blob, hint blob, UNIQUE (coin_id, hint))")

    # Create v2 Tables END

    # Start Data Migration

    # FULL BLOCKS/BLOCK_RECORDS
    # Source Table is ~19 GB/ Source Tables is ~1.3 GB

    print("\n[1/10] converting full_blocks")

    # Cache Size of 1G to write to attached db
    in_db.execute("pragma v2db.cache_size=-1048576")

    rate = 1.0
    start_time = time()
    block_start_time = start_time
    block_values = []

    # Code Snippet to change batch size depending on memory
    # mem = virtual_memory()
    # if mem.available >= MEM_NEEDED_FOR_BLOCKSORT:
    #   in_db.execute("PRAGMA temp_store=MEMORY")
    #   BLOCK_COMMIT_RATE = 100000000
    #   BLOCK_SHRINK_RATE = BLOCK_COMMIT_RATE

    commit_in = BLOCK_COMMIT_RATE
    # shrink_in = BLOCK_SHRINK_RATE

    print(f"\tBlock Commit Rate: {BLOCK_COMMIT_RATE} blocks")

    # TEMP STORE
    # The Temp Table will be created by default to /var/tmp on linux and GetTempPath() on windows
    # Use SQLITE_TMPDIR environment variable to change path (windows?)

    # It could also be necessary to check if enough disk space is available upfront

    # This temp tables are used to bring the source tables into a vacuum-like format
    # On HDD this is very important to reduce runtime, on SSD it is most likely only necessary for block_records
    # Doing this also for full_blocks doesn't always pays back due to the sheer size of the table
    #
    # Maybe check if the DB is on spinning disk, if yes than use temp table for full blocks
    # Or let the user decide during upgrade start?

    # COMMENT IN IF DB is on rotational dev
    #   in_db.execute(
    #            "CREATE TABLE IF NOT EXISTS temp.temp_full_blocks(header_hash text, height bigint,"
    #            "  is_block tinyint, is_fully_compactified tinyint, block blob)"
    #            )

    # No need to use any Primary Keys or such in the temp table, as it is only used as staging area
    in_db.execute(
        "CREATE TABLE IF NOT EXISTS temp.temp_block_records(header_hash "
        "text, prev_hash text, height bigint,"
        "block blob, sub_epoch_summary blob, is_peak tinyint, is_block tinyint)"
    )
    in_db.execute("BEGIN TRANSACTION")
    # COMMENT IN IF DB is on rotational device
    #   in_db.execute("INSERT INTO temp.temp_full_blocks SELECT * from main.full_blocks")
    in_db.execute("INSERT INTO temp.temp_block_records SELECT * from main.block_records")
    reorg_end = time()
    print(f"\tcreate temp table: {reorg_end - start_time:.2f} seconds                             ")
    in_db.commit()

    # TEMP STORE END

    # Recursive query to select from peak backwards ignoring orphaned blocks
    # Using this query, there is no need to fetch block after block and check if it is part of main chain
    cursor = in_db.cursor()
    cursor.execute(
        "WITH RECURSIVE "
        "main_chain(header_hash, height) AS( "
        "SELECT prev_hash, height-1 FROM temp.temp_block_records WHERE header_hash = ? "
        "UNION ALL "
        "SELECT tbr.prev_hash, main_chain.height-1 FROM main_chain, temp.temp_block_records tbr "
        "WHERE main_chain.header_hash = tbr.header_hash "
        "ORDER BY main_chain.height-1 DESC) "
        "SELECT br.header_hash, br.prev_hash, fb.height, br.sub_epoch_summary, "
        "fb.is_fully_compactified, fb.block, br.block "
        # Switch FROM to temp if DB is on rotational dev
        "FROM main.full_blocks fb, temp.temp_block_records br "
        # "FROM temp.temp_full_blocks fb, temp.temp_block_records br "
        "WHERE fb.header_hash = br.header_hash and fb.header_hash = ? "
        "UNION ALL "
        "SELECT br.header_hash, br.prev_hash, fb.height, br.sub_epoch_summary, "
        "fb.is_fully_compactified, fb.block, br.block "
        # Switch FROM to temp if DB is on rotational dev
        "FROM main.full_blocks fb, main_chain bc, temp.temp_block_records br "
        # "FROM temp.temp_full_blocks fb, main_chain bc, temp.temp_block_records br "
        "WHERE bc.header_hash = fb.header_hash AND bc.header_hash = br.header_hash ",
        (peak_hash.hex(), peak_hash.hex()),
    )

    # DATA MIGRATION
    count = 0
    in_db.execute("BEGIN TRANSACTION")
    while True:
        # Use BLOCK_COMMIT_RATE as arraysize fetch argument to increase throughput
        rows = cursor.fetchmany(BLOCK_COMMIT_RATE)
        if not rows:
            break
        for row in rows:
            block_values.append(
                (
                    bytes.fromhex(row[0]),  # header_hash
                    bytes.fromhex(row[1]),  # prev_hash
                    row[2],  # height
                    row[3],  # sub_epoch_summary
                    row[4],  # is_fully_compactified
                    1,  # in_main_chain
                    zstd.compress(row[5]),  # full block
                    row[6],  # block records
                )
            )
            count += 1
            if ((peak_height - count) % 10000) == 0:
                print(
                    f"\r\tProcessing Blocks, to do: {(peak_height - count): 10d}, {(count)/peak_height*100:.2f}% done, "
                    f"{rate:0.1f} blocks/s ETA: {count//rate} s    ",
                    end="",
                )
                sys.stdout.flush()
            commit_in -= 1
            if commit_in == 0:
                commit_in = BLOCK_COMMIT_RATE
                #               commit_start = time()
                in_db.executemany("INSERT INTO v2db.full_blocks VALUES(?, ?, ?, ?, ?, ?, ?, ?)", block_values)
                in_db.commit()
                #               commit_end = time()
                #               print(f"\rTime to commit: {commit_end - commit_start:.2f} seconds")
                in_db.execute("BEGIN TRANSACTION")
                block_values = []
                end_time = time()
                rate = BLOCK_COMMIT_RATE / (end_time - start_time)
                start_time = end_time
    #           shrink_in -= 1
    #           if shrink_in <= 0:
    #               shrink_in = BLOCK_COMMIT_RATE
    #               shrink_start = time()
    #               in_db.execute("PRAGMA shrink_memory")
    #               shrink_end = time()
    #               print(f"\rTime to shrink: {shrink_end - shrink_start:.2f} seconds")

    in_db.executemany("INSERT INTO v2db.full_blocks VALUES(?, ?, ?, ?, ?, ?, ?, ?)", block_values)
    in_db.commit()
    cursor.close()

    full_blocks_end_time = time()
    print(f"\n\tOverall Time: {full_blocks_end_time - block_start_time:.2f} seconds")

    # INDEXES BLOCK STORE START
    print("\n[2/10] recreating block store indexes")
    # Found out having best performance on index rebuild using small cache size
    in_db.execute("pragma v2db.cache_size=-2000")

    # 1. INDEX
    block_store_start = time()
    in_db.execute("CREATE INDEX IF NOT EXISTS v2db.height on full_blocks(height)")
    block_height_end = time()
    print(f"\tCreate Index on height: {block_height_end - block_store_start:.2f} seconds ")

    # 2. INDEX
    in_db.execute(
        "CREATE INDEX IF NOT EXISTS v2db.is_fully_compactified ON"
        " full_blocks(is_fully_compactified, in_main_chain) WHERE in_main_chain=1"
    )
    block_compmain_end = time()
    print(f"\tCreate Index on is_fully_compact/main_chain: {block_compmain_end - block_height_end:.2f} seconds ")

    # 3. INDEX
    in_db.execute(
        "CREATE INDEX IF NOT EXISTS v2db.main_chain ON full_blocks(height, in_main_chain) WHERE in_main_chain=1"
    )
    block_heightmain_end = time()
    print(f"\tCreate Index on height/main_chain: {block_heightmain_end - block_compmain_end:.2f} seconds ")

    # Leftover of non-PK test
    # 4. INDEX
    #   in_db.execute(
    #       "CREATE UNIQUE INDEX IF NOT EXISTS v2db.fb_header_hash ON full_blocks(header_hash)"
    #   )
    block_store_end = time()
    #   print(f"\tCreate Unique Index on header_hash: {block_store_end - block_heightmain_end:.2f} seconds ")

    print(f"\tOverall Indexes: {block_store_end - block_store_start:.2f} seconds ")
    # INDEXES BLOCK STORE END

    in_db.close()
    ############

    # Reconnect to get new mmap initalization for new table
    temp2_out_path = out_path_string.replace("blockchain_v2_mainnet.sqlite", "temp_coin_store.sqlite")
    temp2_db = connect_to_db(in_path, temp2_out_path)

    # COIN_RECORD
    # Source Table is ~9.5G
    print("\n[3/10] converting coin_store")

    temp2_db.execute("pragma v2db.cache_size=-1048576")

    rate = 1.0
    start_time = time()
    coin_values = []
    coin_start_time = start_time

    commit_in = COIN_COMMIT_RATE
    #   shrink_in = COIN_SHRINK_RATE

    print(f"\tCoin Commit Rate: {COIN_COMMIT_RATE} blocks")

    # TEMP STORE
    # No PK on temp stage needed
    temp2_db.execute(
        "CREATE TEMP TABLE IF NOT EXISTS temp.temp_coin_record("
        "coin_name text,"
        " confirmed_index bigint,"
        " spent_index bigint,"
        " spent int,"
        " coinbase int,"
        " puzzle_hash text,"
        " coin_parent text,"
        " amount blob,"
        " timestamp bigint)"
    )
    temp2_db.execute("BEGIN TRANSACTION")
    temp2_db.execute("INSERT INTO temp.temp_coin_record SELECT * from main.coin_record")
    reorg_end = time()
    print(f"\tCreate Temp Table: {reorg_end - coin_start_time:.2f} seconds                             ")
    temp2_db.commit()
    # TEMP STORE END

    # Coin Record Table in temp db file
    # Also there is no PK needed in the temporary used sqlite file, the final table will have PK again
    temp2_db.execute(
        "CREATE TABLE IF NOT EXISTS v2db.coin_record("
        "coin_name blob,"
        "confirmed_index bigint,"
        "spent_index bigint,"  # if this is zero, it means the coin has not been spent
        "coinbase int,"
        "puzzle_hash blob,"
        "coin_parent blob,"
        "amount blob,"  # we use a blob of 8 bytes to store uint64
        "timestamp bigint)"
    )

    cursor = temp2_db.cursor()
    cursor.execute(
        "SELECT coin_name, confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount, timestamp "
        "FROM temp.temp_coin_record WHERE confirmed_index <= ?",
        (peak_height,),
    )

    # DATA MIGRATION

    count = 0
    temp2_db.execute("BEGIN TRANSACTION")
    while True:
        rows = cursor.fetchmany(COIN_COMMIT_RATE)
        if not rows:
            break
        for row in rows:
            # The following part was in the original upgrade script
            # Not sure if this was necessary,
            # as the fetching query already had a condition where confirmed_index <= peak

            # in order to convert a consistent snapshot of the
            # blockchain state, any coin that was spent *after* our
            # cutoff must be converted into an unspent coin
            # if spent_index > peak_height:
            #    spent_index = 0

            coin_values.append(
                (
                    bytes.fromhex(row[0]),
                    row[1],
                    row[2],
                    row[3],
                    bytes.fromhex(row[4]),
                    bytes.fromhex(row[5]),
                    row[6],
                    row[7],
                )
            )
            count += 1
            if (count % 100000) == 0:
                print(f"\r{count//1000:10d}k coins {rate:0.1f} coins/s  ", end="")
                sys.stdout.flush()
            commit_in -= 1
            if commit_in == 0:
                commit_in = COIN_COMMIT_RATE
                temp2_db.executemany("INSERT INTO v2db.coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)", coin_values)
                temp2_db.commit()
                temp2_db.execute("BEGIN TRANSACTION")
                coin_values = []
                end_time = time()
                rate = COIN_COMMIT_RATE / (end_time - start_time)
                start_time = end_time
    #        shrink_in -= 1
    #        if shrink_in <= 0:
    #            shrink_in = COIN_COMMIT_RATE
    #            temp2_db.execute("PRAGMA shrink_memory")

    temp2_db.executemany("INSERT INTO v2db.coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)", coin_values)
    temp2_db.commit()
    cursor.close()
    end_time = time()
    print(f"\tOverall Time: {end_time - coin_start_time:.2f} seconds")

    temp2_db.close()
    ###############

    # Again recoonnect to get benefit of mmap
    temp3_out_path = out_path_string.replace("blockchain_v2_mainnet.sqlite", "temp_sub_epoch.sqlite")
    temp3_db = connect_to_db(in_path, temp3_out_path)

    # SUB_EPOCH_SEGMENTS_V3
    # Source Table is 2.4G
    print("\n[4/10] converting sub_epoch_segments_v3")

    # Sub Epoch table also benefits when using cache size on source db file
    temp3_db.execute("pragma main.cache_size=-102400")
    temp3_db.execute("pragma v2db.cache_size=-102400")

    ses_values = []
    ses_start_time = time()

    commit_in = SES_COMMIT_RATE
    #   shrink_in = SES_SHRINK_RATE

    print(f"\tSub Epoch Commit Rate: {SES_COMMIT_RATE} blocks")

    # Sub Epoch Table in temp db file
    temp3_db.execute(
        "CREATE TABLE IF NOT EXISTS v2db.sub_epoch_segments_v3(" "ses_block_hash blob," "challenge_segments blob)"
    )

    cursor = temp3_db.cursor()
    cursor.execute("SELECT ses_block_hash, challenge_segments FROM main.sub_epoch_segments_v3")

    # DATA MIGRATION

    count = 0
    temp3_db.execute("BEGIN TRANSACTION")
    while True:
        rows = cursor.fetchmany(SES_COMMIT_RATE)
        if not rows:
            break
        for row in rows:
            ses_values.append(
                (
                    bytes32.fromhex(row[0]),
                    row[1],
                )
            )
            count += 1
            if (count % 100) == 0:
                print(f"\r{count:10d}  ", end="")
                sys.stdout.flush()

            commit_in -= 1
            if commit_in == 0:
                commit_in = SES_COMMIT_RATE
                temp3_db.executemany("INSERT INTO v2db.sub_epoch_segments_v3 VALUES (?, ?)", ses_values)
                temp3_db.commit()
                temp3_db.execute("BEGIN TRANSACTION")
                ses_values = []
    #        shrink_in -= 1
    #        if shrink_in <= 0:
    #            shrink_in = SES_COMMIT_RATE
    #            temp3_db.execute("PRAGMA shrink_memory")

    temp3_db.executemany("INSERT INTO v2db.sub_epoch_segments_v3 VALUES (?, ?)", ses_values)
    temp3_db.commit()
    cursor.close()
    end_time = time()
    print(f"\tOverall Time: {end_time - ses_start_time:.2f} seconds")

    temp3_db.close()
    ###############

    # At this point, data conversion is finished
    # full_blocks table is already converted and migrated to target v2 file
    # coin_record and sub_epoch tables are converted and stored in temp sqlite db file
    # and will be migrated to target db file now
    print(f"\nstarting migration to final db file: {out_path}")

    print("\n[5/10] migrating temp table coin_record")
    in_db = connect_to_db(Path(temp2_out_path), out_path_string)

    # Setting explicitly lower cache_spill to prevent to much memory usage
    # Be aware that these settings should all lead to a max use of 4G memory,
    # so need to be adjusted for smaller sized nodes
    in_db.execute("pragma v2db.cache_spill=100000")
    in_db.execute("pragma v2db.cache_size=-524288")

    # COIN_RECORD START
    reorg_start = time()
    in_db.execute("BEGIN TRANSACTION")
    # Important order by coin_name so we don't have a big impact on the enabled primary key
    in_db.execute("INSERT INTO v2db.coin_record SELECT * from main.coin_record order by coin_name")
    reorg_end = time()
    print(f"\tMigrate coin_record: {reorg_end - reorg_start:.2f} seconds                             ")
    in_db.commit()
    # COIN_RECORD END

    # INDEXES
    print("\n[6/10] Recreating coin store indexes")
    in_db.execute("pragma v2db.cache_size=-2000")

    # 1. INDEX
    coin_store_start = time()
    in_db.execute("CREATE INDEX IF NOT EXISTS v2db.coin_puzzle_hash on coin_record(puzzle_hash)")
    coin_puzzle_end = time()
    print(
        f"\tCreate Index on puzzle_hash: {coin_puzzle_end - coin_store_start:.2f} seconds                             "
    )

    # 2. INDEX
    in_db.execute("CREATE INDEX IF NOT EXISTS v2db.coin_parent_index on coin_record(coin_parent)")
    coin_parent_end = time()
    print(
        f"\tCreate Index on coin_parent: {coin_parent_end - coin_puzzle_end:.2f} seconds                             "
    )

    # 3. INDEX
    in_db.execute("CREATE INDEX IF NOT EXISTS v2db.coin_confirmed_index on coin_record(confirmed_index)")
    coin_conf_end = time()
    print(
        f"\tCreate Index on confirmed index: {coin_conf_end - coin_parent_end:.2f} seconds                             "
    )

    # 4. INDEX
    in_db.execute("CREATE INDEX IF NOT EXISTS v2db.coin_spent_index on coin_record(spent_index)")
    coin_spent_end = time()
    print(f"\tCreate Index on spent_index: {coin_spent_end - coin_conf_end:.2f} seconds                             ")

    # 5. INDEX
    #   in_db.execute("CREATE UNIQUE INDEX IF NOT EXISTS v2db.cr_coin_name on coin_record(coin_name)")
    coin_name_end = time()
    #   print(f"\tCreate Unique Index on coin_name: {coin_name_end - coin_spent_end:.2f} seconds                  ")

    print(f"\tOverall Index Rebuild: {coin_name_end - coin_store_start:.2f} seconds                             ")

    in_db.close()
    remove(temp2_out_path)
    ############

    print("\n[7/10] migrating temp table sub_epoch_segments_v3")
    in_db = connect_to_db(Path(temp3_out_path), out_path_string)

    in_db.execute("pragma v2db.cache_spill=100000")
    in_db.execute("pragma v2db.cache_size=-102400")
    in_db.execute("pragma main.cache_size=-102400")

    # SUB_EPOCH_SEGMENTS_V3 START
    reorg_start = time()
    in_db.execute("BEGIN TRANSACTION")
    in_db.execute("INSERT INTO v2db.sub_epoch_segments_v3 SELECT * from main.sub_epoch_segments_v3")
    reorg_end = time()
    print(f"\tMigrate sub_epoch_segments_v3: {reorg_end - reorg_start:.2f} seconds                             ")
    in_db.commit()
    # SUB_EPOCH_SEGMENTS_V3 END

    # INDEXES
    print("\n[8/10] Recreating sub_epoch_segments_v3 indexes")
    in_db.execute("pragma v2db.cache_size=-2000")

    # 1. INDEX
    #   ses_start = time()
    #   in_db.execute("CREATE UNIQUE INDEX IF NOT EXISTS v2db.ses_block_hash on sub_epoch_segments_v3(ses_block_hash)")
    #   ses_end = time()
    #   print(f"\tCreate Unique Index on ses_block_hash: {ses_end - ses_start:.2f} seconds                          ")

    in_db.close()
    remove(temp3_out_path)
    ############

    # HINTS
    # Source Table is 40M
    print("\n[9/10] converting hint_store")
    in_db = connect_to_db(in_path, out_path_string)

    in_db.execute("pragma v2db.cache_size=-1048576")

    commit_in = HINT_COMMIT_RATE
    #   shrink_in = HINT_SHRINK_RATE

    print(f"\tHint Commit Rate: {HINT_COMMIT_RATE} blocks")

    hint_start_time = time()
    hint_values = []

    cursor = in_db.cursor()
    cursor.execute("SELECT coin_id, hint FROM main.hints")

    # DATA MIGRATION

    count = 0
    in_db.execute("BEGIN TRANSACTION")
    while True:
        rows = cursor.fetchmany(HINT_COMMIT_RATE)
        if not rows:
            break
        for row in rows:
            hint_values.append((row[0], row[1]))
            commit_in -= 1
            if commit_in == 0:
                commit_in = HINT_COMMIT_RATE
                in_db.executemany("INSERT INTO v2db.hints VALUES (?, ?) ON CONFLICT DO NOTHING", hint_values)
                in_db.commit()
                in_db.execute("BEGIN TRANSACTION")
                hint_values = []
    #        shrink_in -= 1
    #        if shrink_in <= 0:
    #            shrink_in = HINT_COMMIT_RATE
    #            in_db.execute("PRAGMA shrink_memory")

    in_db.executemany("INSERT INTO v2db.hints VALUES (?, ?) ON CONFLICT DO NOTHING", hint_values)
    in_db.commit()
    cursor.close()
    end_time = time()
    print(f"\tOverall Time: {end_time - hint_start_time:.2f} seconds                             ")

    # INDEXES
    print("\n[10/10] recreating hints indexes")

    in_db.execute("pragma v2db.cache_size=-2000")

    hint_store_start = time()
    in_db.execute("CREATE INDEX IF NOT EXISTS v2db.hint_index on hints(hint)")
    hint_store_end = time()
    print(f"\tCreate Index on hint: {hint_store_end - hint_store_start:.2f} seconds                             ")

    print("\nFinalize upgrade")
    # Update DB Version
    in_db.execute("UPDATE v2db.database_version SET version=?", (2,))
    in_db.commit()
    print("\nUpgrade finished.")
