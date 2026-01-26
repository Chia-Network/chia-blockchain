from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from chia.daemon.server import service_launch_lock_path
from chia.util.config import load_config
from chia.util.lock import Lockfile, LockfileError
from chia.util.path import path_from_root


def db_prune_func(
    root_path: Path,
    in_db_path: Path | None = None,
    *,
    blocks_back: int = 300,
) -> None:
    """
    Prune the blockchain database by removing blocks from the peak.

    This removes the most recent blocks_back blocks from the peak, making
    the block at (peak_height - blocks_back) the new peak when full_node restarts.
    It will refuse to run if the full_node service is currently running.
    """
    # Check if full_node is running by trying to acquire its lock
    full_node_lock_path = service_launch_lock_path(root_path, "chia_full_node")
    try:
        with Lockfile.create(full_node_lock_path, timeout=0.1):
            # We got the lock, so full_node is not running
            pass
    except LockfileError:
        raise RuntimeError(
            "Cannot prune database while full_node is running. "
            "Please stop the full_node service first with 'chia stop node'"
        )

    config: dict[str, Any] = load_config(root_path, "config.yaml")["full_node"]
    if in_db_path is None:
        selected_network: str = config["selected_network"]
        db_pattern: str = config["database_path"]
        db_path_replaced: str = db_pattern.replace("CHALLENGE", selected_network)
        in_db_path = path_from_root(root_path, db_path_replaced)

    prune_db(in_db_path, blocks_back=blocks_back)


def prune_db(db_path: Path, *, blocks_back: int) -> None:
    """
    Prune the database by removing the most recent blocks_back blocks from the peak.

    This removes blocks at height > (peak_height - blocks_back), making the block
    at (peak_height - blocks_back) the new peak when full_node is restarted.
    Also removes any orphan blocks at those heights and cleans up related data
    (coin records, hints) so the node can sync forward correctly.
    """
    if not db_path.exists():
        raise RuntimeError(f"Database file does not exist: {db_path}")

    print(f"Opening database: {db_path}")

    with closing(sqlite3.connect(db_path)) as conn:
        # Check database version
        try:
            with closing(conn.execute("SELECT * FROM database_version")) as cursor:
                row = cursor.fetchone()
                if row is None or row == []:
                    raise RuntimeError("Database is missing version field")
                if row[0] != 2:
                    raise RuntimeError(f"Database has the wrong version ({row[0]} expected 2)")
        except sqlite3.OperationalError:
            raise RuntimeError("Database is missing version table")

        # Get the peak height
        try:
            with closing(conn.execute("SELECT hash FROM current_peak WHERE key = 0")) as cursor:
                row = cursor.fetchone()
                if row is None or row == []:
                    raise RuntimeError("Database is missing current_peak")
                peak_hash = row[0]
        except sqlite3.OperationalError:
            raise RuntimeError("Database is missing current_peak table")

        with closing(conn.execute("SELECT height FROM full_blocks WHERE header_hash = ?", (peak_hash,))) as cursor:
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("Database is missing the peak block")
            peak_height = row[0]

        print(f"Current peak height: {peak_height}")

        if blocks_back >= peak_height:
            print(f"blocks_back ({blocks_back}) >= peak_height ({peak_height}). Nothing to prune.")
            return

        new_peak_height = peak_height - blocks_back

        print(f"Pruning {blocks_back} blocks from height {new_peak_height + 1} to {peak_height}")
        print(f"Block at height {new_peak_height} will become the new peak")

        # Get the new peak hash (the block at new_peak_height in the main chain)
        with closing(
            conn.execute(
                "SELECT header_hash FROM full_blocks WHERE height = ? AND in_main_chain = 1",
                (new_peak_height,),
            )
        ) as cursor:
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError(f"Cannot find main chain block at height {new_peak_height}")
            new_peak_hash = row[0]

        # Count blocks to be deleted (all blocks above new_peak_height)
        with closing(
            conn.execute(
                "SELECT COUNT(*) FROM full_blocks WHERE height > ?",
                (new_peak_height,),
            )
        ) as cursor:
            total_blocks_to_delete = cursor.fetchone()[0]

        if total_blocks_to_delete == 0:
            print("No blocks to prune.")
            return

        print(f"Blocks to prune: {total_blocks_to_delete}")

        # Clean up coin_record and hints tables if they exist
        # This is necessary for the node to sync forward correctly after pruning
        try:
            print("Cleaning up coin records and hints...")

            # 1. Delete hints for coins that will be deleted (must do this BEFORE deleting coins)
            try:
                with closing(
                    conn.execute(
                        "SELECT COUNT(*) FROM hints WHERE coin_id IN "
                        "(SELECT coin_name FROM coin_record WHERE confirmed_index > ?)",
                        (new_peak_height,),
                    )
                ) as cursor:
                    hints_to_delete = cursor.fetchone()[0]
                if hints_to_delete > 0:
                    print(f"  Deleting {hints_to_delete} hints for coins above height {new_peak_height}...")
                    conn.execute(
                        "DELETE FROM hints WHERE coin_id IN "
                        "(SELECT coin_name FROM coin_record WHERE confirmed_index > ?)",
                        (new_peak_height,),
                    )
                    conn.commit()
            except sqlite3.OperationalError:
                # hints table might not exist in all databases
                pass

            # 2. Delete coins that were created (confirmed) at heights above new_peak_height
            with closing(
                conn.execute("SELECT COUNT(*) FROM coin_record WHERE confirmed_index > ?", (new_peak_height,))
            ) as cursor:
                coins_to_delete = cursor.fetchone()[0]

            if coins_to_delete > 0:
                print(f"  Deleting {coins_to_delete} coin records created above height {new_peak_height}...")
                # Delete in batches for large databases using rowid
                coin_batch_size = 1000
                deleted_coins = 0
                while True:
                    conn.execute(
                        "DELETE FROM coin_record WHERE rowid IN "
                        "(SELECT rowid FROM coin_record WHERE confirmed_index > ? LIMIT ?)",
                        (new_peak_height, coin_batch_size),
                    )
                    conn.commit()
                    # Check how many are left
                    with closing(
                        conn.execute("SELECT COUNT(*) FROM coin_record WHERE confirmed_index > ?", (new_peak_height,))
                    ) as cursor:
                        remaining = cursor.fetchone()[0]
                    deleted_coins = coins_to_delete - remaining
                    if remaining == 0:
                        break
                    print(f"\r    Deleted {deleted_coins}/{coins_to_delete} coin records...", end="", flush=True)
                print(f"\r    Deleted {deleted_coins} coin records.                    ")

            # 3. Reset spent_index for coins that were spent at heights above new_peak_height
            #    (they need to become unspent again)
            with closing(
                conn.execute("SELECT COUNT(*) FROM coin_record WHERE spent_index > ?", (new_peak_height,))
            ) as cursor:
                coins_to_unspend = cursor.fetchone()[0]

            if coins_to_unspend > 0:
                print(f"  Resetting {coins_to_unspend} coin records that were spent above height {new_peak_height}...")
                # Reset spent_index for coins spent above the new peak.
                # If the coin is not a reward coin (coinbase=0) and its parent has
                # the same puzzle_hash and amount and is spent, set spent_index to -1
                # to preserve fast-forward singleton state. Otherwise set to 0.
                # This matches the logic in coin_store.py rollback_to_block.
                conn.execute(
                    """
                    UPDATE coin_record
                    SET spent_index = CASE
                        WHEN
                            coinbase = 0 AND
                            EXISTS (
                                SELECT 1
                                FROM coin_record AS parent
                                WHERE
                                    parent.coin_name = coin_record.coin_parent AND
                                    parent.puzzle_hash = coin_record.puzzle_hash AND
                                    parent.amount = coin_record.amount AND
                                    parent.spent_index > 0
                            )
                        THEN -1
                        ELSE 0
                    END
                    WHERE spent_index > ?
                    """,
                    (new_peak_height,),
                )
                conn.commit()
                print(f"    Reset {coins_to_unspend} coin records.")
        except sqlite3.OperationalError:
            # coin_record table might not exist in minimal test databases
            pass

        # Delete blocks in batches to show progress
        print("Deleting blocks...")
        batch_size = 1000
        deleted = 0

        while True:
            conn.execute(
                "DELETE FROM full_blocks WHERE height > ? AND rowid IN "
                "(SELECT rowid FROM full_blocks WHERE height > ? LIMIT ?)",
                (new_peak_height, new_peak_height, batch_size),
            )
            conn.commit()

            rows_deleted = conn.total_changes - deleted
            if rows_deleted == 0:
                break
            deleted = conn.total_changes
            print(f"\r  Deleted {deleted}/{total_blocks_to_delete} blocks...", end="", flush=True)

        print(f"\r  Deleted {deleted} blocks.                              ")

        # Update the current_peak to point to the new peak
        conn.execute("UPDATE current_peak SET hash = ? WHERE key = 0", (new_peak_hash,))
        conn.commit()
        print(f"Updated peak to height {new_peak_height}")

        # Get the new database info
        with closing(conn.execute("SELECT COUNT(*) FROM full_blocks")) as cursor:
            remaining_blocks = cursor.fetchone()[0]

        with closing(
            conn.execute("SELECT MIN(height), MAX(height) FROM full_blocks WHERE in_main_chain = 1")
        ) as cursor:
            row = cursor.fetchone()
            min_height = row[0]
            max_height = row[1]

        try:
            with closing(conn.execute("SELECT COUNT(*) FROM coin_record")) as cursor:
                remaining_coins = cursor.fetchone()[0]
            coin_count_msg = f"Remaining coin records: {remaining_coins}"
        except sqlite3.OperationalError:
            coin_count_msg = ""

        print(f"Remaining blocks in database: {remaining_blocks}")
        print(f"Main chain height range: {min_height} to {max_height}")
        if coin_count_msg:
            print(coin_count_msg)
        print("\nPruning complete. Run 'VACUUM' on the database to reclaim disk space if desired.")
        print("You can do this with: chia db backup")
        print("Then replace the original database with the backup.")
