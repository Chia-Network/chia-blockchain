from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any

from chia.daemon.server import service_launch_lock_path
from chia.util.config import load_config
from chia.util.lock import Lockfile, LockfileError
from chia.util.path import path_from_root

# Number of spots to sample in the DB when doing a fast integrity check.
_INTEGRITY_CHECK_SAMPLES = 10


def _is_missing_table_or_column(e: sqlite3.OperationalError) -> bool:
    """Return True if the error indicates a missing table or column (optional schema)."""
    msg = str(e).lower()
    return "no such table" in msg or "no such column" in msg


def db_prune_func(
    root_path: Path,
    in_db_path: Path | None = None,
    *,
    blocks_back: int = 300,
    skip_integrity_check: bool = False,
    full_integrity_check: bool = False,
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

    # Run read-only integrity check before acquiring the lock so we don't hold the
    # lock for hours with --full-integrity-check on very large databases.
    if not skip_integrity_check and in_db_path.exists():
        with closing(sqlite3.connect(in_db_path)) as conn:
            if full_integrity_check:
                _run_full_integrity_check(conn)
            else:
                _run_sampled_integrity_check(conn)

    # Acquire the full_node lock and hold it for the prune mutations only.
    full_node_lock_path = service_launch_lock_path(root_path, "chia_full_node")
    try:
        with Lockfile.create(full_node_lock_path, timeout=0.1):
            try:
                prune_db(
                    in_db_path,
                    blocks_back=blocks_back,
                    skip_integrity_check=True,  # already done above if applicable
                    full_integrity_check=full_integrity_check,
                )
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


def _run_sampled_integrity_check(conn: sqlite3.Connection) -> None:
    """
    Run a fast sampled integrity check by reading from 10 different spots
    in the database. Catches obvious corruption without a full PRAGMA integrity_check.
    """
    # Queries that each read one row from different tables/positions.
    # All use LIMIT 1; small OFFSETs are fast. Optional tables (hints, sub_epoch_segments_v3)
    # may not exist in minimal DBs and are skipped.
    checks: list[tuple[str, str]] = [
        ("database_version", "SELECT * FROM database_version LIMIT 1"),
        ("current_peak", "SELECT hash FROM current_peak WHERE key = 0"),
        ("full_blocks (start)", "SELECT 1 FROM full_blocks LIMIT 1"),
        ("full_blocks (offset 1)", "SELECT 1 FROM full_blocks LIMIT 1 OFFSET 1"),
        ("full_blocks (offset 2)", "SELECT 1 FROM full_blocks LIMIT 1 OFFSET 2"),
        ("full_blocks (offset 3)", "SELECT 1 FROM full_blocks LIMIT 1 OFFSET 3"),
        ("full_blocks (offset 4)", "SELECT 1 FROM full_blocks LIMIT 1 OFFSET 4"),
        ("full_blocks (offset 5)", "SELECT 1 FROM full_blocks LIMIT 1 OFFSET 5"),
        ("coin_record", "SELECT 1 FROM coin_record LIMIT 1"),
        ("hints or full_blocks", "SELECT 1 FROM hints LIMIT 1"),
    ]
    assert len(checks) == _INTEGRITY_CHECK_SAMPLES

    print(
        f"Running sampled integrity check ({_INTEGRITY_CHECK_SAMPLES} spots)...",
        flush=True,
    )
    for name, sql in checks:
        try:
            with closing(conn.execute(sql)) as cursor:
                cursor.fetchone()
        except sqlite3.OperationalError as e:
            # Table might not exist for optional checks (e.g. hints)
            if _is_missing_table_or_column(e):
                if "hints" in sql:
                    # Fallback: one more full_blocks read so we still sample 10 spots
                    with closing(conn.execute("SELECT 1 FROM full_blocks LIMIT 1 OFFSET 6")) as cursor:
                        cursor.fetchone()
                continue
            raise RuntimeError(f"Database integrity check failed at {name}: {e}") from e
    print(" ok", flush=True)


def _run_full_integrity_check(conn: sqlite3.Connection) -> None:
    """
    Run PRAGMA integrity_check over the entire database. Slow on large DBs;
    prints progress dots every 30 seconds so the user sees activity.
    """
    done = threading.Event()

    def _progress_dots() -> None:
        while not done.wait(timeout=30):
            print(".", end="", flush=True)

    print(
        "Running full integrity check (this may take a long time on large databases)...",
        flush=True,
    )
    progress_thread = threading.Thread(target=_progress_dots, daemon=True)
    progress_thread.start()
    try:
        with closing(conn.execute("PRAGMA integrity_check")) as cursor:
            result = cursor.fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"Database integrity check failed: {result}")
    finally:
        done.set()
        progress_thread.join(timeout=1)
    print(" ok", flush=True)


def prune_db(
    db_path: Path,
    *,
    blocks_back: int,
    skip_integrity_check: bool = False,
    full_integrity_check: bool = False,
) -> None:
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
        # Validate required schema first so minimal DBs fail with clear RuntimeError
        # before we run the integrity check (which touches full_blocks).
        try:
            with closing(conn.execute("SELECT * FROM database_version")) as cursor:
                row = cursor.fetchone()
                if row is None or row == []:
                    raise RuntimeError("Database is missing version field")
                if row[0] != 2:
                    raise RuntimeError(f"Database has the wrong version ({row[0]} expected 2)")
        except sqlite3.OperationalError:
            raise RuntimeError("Database is missing version table")

        try:
            with closing(conn.execute("SELECT hash FROM current_peak WHERE key = 0")) as cursor:
                row = cursor.fetchone()
                if row is None or row == []:
                    raise RuntimeError("Database is missing current_peak")
                peak_hash = row[0]
        except sqlite3.OperationalError:
            raise RuntimeError("Database is missing current_peak table")

        try:
            with closing(conn.execute("SELECT height FROM full_blocks WHERE header_hash = ?", (peak_hash,))) as cursor:
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("Database is missing the peak block")
                peak_height = row[0]
        except sqlite3.OperationalError:
            raise RuntimeError("Database is missing full_blocks table")

        print(f"Current peak height: {peak_height}")

        if not skip_integrity_check:
            if full_integrity_check:
                _run_full_integrity_check(conn)
            else:
                _run_sampled_integrity_check(conn)
        else:
            print("Skipping integrity check.", flush=True)

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
                print(".", end="", flush=True)
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
            except sqlite3.OperationalError as e:
                if not _is_missing_table_or_column(e):
                    raise
                # hints table might not exist

            # Delete coin records confirmed above new peak.
            print("Deleting coin records...")
            try:
                conn.execute(
                    "DELETE FROM coin_record WHERE confirmed_index > ?",
                    (new_peak_height,),
                )
            except sqlite3.OperationalError as e:
                if not _is_missing_table_or_column(e):
                    raise
                # coin_record table might not exist in minimal DBs

            # Reset spent_index for coins spent above new peak (make them unspent).
            # Use 0 for unspent: coin_store treats any spent_index <= 0 as unspent and
            # normalizes to 0 in CoinRecord (see coin_store row handling). The -1
            # fast-forward singleton hint is an optimization only; it is recalculated
            # on the next rollback_to_block() or when new_block() adds coins. Using
            # 0 does not cause UNKNOWN_UNSPENT during resync; get_coin_records() looks
            # up by coin_name and returns these coins as unspent.
            print("Resetting spent coin records...")
            try:
                conn.execute(
                    """
                    UPDATE coin_record
                    SET spent_index = 0
                    WHERE spent_index > ?
                    """,
                    (new_peak_height,),
                )
            except sqlite3.OperationalError as e:
                if not _is_missing_table_or_column(e):
                    raise
                # coin_record table might not exist in minimal DBs

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
            except sqlite3.OperationalError as e:
                if not _is_missing_table_or_column(e):
                    raise
                # table might not exist

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
