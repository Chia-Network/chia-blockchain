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
    if in_db_path is None:
        config: dict[str, Any] = load_config(root_path, "config.yaml")["full_node"]
        selected_network: str = config["selected_network"]
        db_pattern: str = config["database_path"]
        db_path_replaced: str = db_pattern.replace("CHALLENGE", selected_network)
        in_db_path = path_from_root(root_path, db_path_replaced)

    # Acquire the full_node lock and hold it for the entire prune operation.
    # This prevents full_node from starting while we're modifying the database.
    full_node_lock_path = service_launch_lock_path(root_path, "chia_full_node")
    try:
        with Lockfile.create(full_node_lock_path, timeout=0.1):
            try:
                prune_db(in_db_path, blocks_back=blocks_back)
            except RuntimeError:
                raise
            except sqlite3.Error as e:
                raise RuntimeError(f"Database error during prune: {e}")
            except Exception as e:
                raise RuntimeError(f"Unexpected error during prune: {e}")
    except LockfileError:
        raise RuntimeError(
            "Cannot prune database while full_node is running. "
            "Please stop the full_node service first with 'chia stop node'"
        )


def prune_db(db_path: Path, *, blocks_back: int) -> None:
    """
    Prune the database by removing the most recent blocks_back blocks from the peak.

    This removes blocks at height > (peak_height - blocks_back), making the block
    at (peak_height - blocks_back) the new peak when full_node is restarted.
    Also removes any orphan blocks at those heights and cleans up related data
    (coin records, hints) so the node can sync forward correctly.
    """
    if blocks_back < 0:
        raise RuntimeError(f"blocks_back must be a non-negative integer, got {blocks_back}")

    if not db_path.exists():
        raise RuntimeError(f"Database file does not exist: {db_path}")

    print(f"Opening database: {db_path}")

    with closing(sqlite3.connect(db_path)) as conn:
        with closing(conn.execute("PRAGMA integrity_check")) as cursor:
            result = cursor.fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"Database integrity check failed: {result}")

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

        if blocks_back > peak_height:
            print(f"blocks_back ({blocks_back}) > peak_height ({peak_height}). Nothing to prune.")
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

        # Single transaction: all mutations in one BEGIN IMMEDIATE / commit.
        # Progress handler prints dots during long operations so the user sees activity.
        progress_count: list[int] = [0]

        def _progress_callback() -> int:
            progress_count[0] += 1
            if progress_count[0] % 10 == 0:
                print(".", flush=True)
            return 0

        conn.execute("BEGIN IMMEDIATE")
        conn.set_progress_handler(_progress_callback, 10000)
        try:
            # Update peak first (crash safety: peak points to valid block).
            print("Updating peak...")
            conn.execute("UPDATE current_peak SET hash = ? WHERE key = 0", (new_peak_hash,))

            # Delete hints for coins that will be deleted (must be before deleting coins).
            print("Deleting hints...")
            try:
                conn.execute(
                    "DELETE FROM hints WHERE coin_id IN (SELECT coin_name FROM coin_record WHERE confirmed_index > ?)",
                    (new_peak_height,),
                )
            except sqlite3.OperationalError:
                pass  # hints table might not exist

            # Delete coin records confirmed above new peak.
            print("Deleting coin records...")
            try:
                conn.execute(
                    "DELETE FROM coin_record WHERE confirmed_index > ?",
                    (new_peak_height,),
                )
            except sqlite3.OperationalError:
                pass  # coin_record table might not exist in minimal DBs

            # Reset spent_index for coins spent above new peak (make them unspent).
            print("Resetting spent coin records...")
            try:
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
            except sqlite3.OperationalError:
                pass

            # Delete blocks above new peak.
            print("Deleting blocks...")
            conn.execute("DELETE FROM full_blocks WHERE height > ?", (new_peak_height,))

            # Clean up sub_epoch_segments for blocks that no longer exist.
            print("Cleaning up sub-epoch segments...")
            try:
                conn.execute(
                    "DELETE FROM sub_epoch_segments_v3 WHERE ses_block_hash NOT IN "
                    "(SELECT header_hash FROM full_blocks)"
                )
            except sqlite3.OperationalError:
                pass  # table might not exist

            conn.commit()

            # Summary (read after commit).
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

            print(f"\nRemaining blocks in database: {remaining_blocks}")
            print(f"Main chain height range: {min_height} to {max_height}")
            if coin_count_msg:
                print(coin_count_msg)
            print("\nPruning complete. Run 'VACUUM' on the database to reclaim disk space if desired.")
            print("You can do this with: chia db backup")
            print("Then replace the original database with the backup.")

        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Prune failed: {e}")
        finally:
            conn.set_progress_handler(None, 0)
