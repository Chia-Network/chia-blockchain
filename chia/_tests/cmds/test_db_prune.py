from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from chia_rs.sized_bytes import bytes32
from click.testing import CliRunner

from chia._tests.util.temp_file import TempFile
from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.db import db_cmd, db_prune_cmd
from chia.cmds.db_prune_func import db_prune_func, prune_db
from chia.util.lock import Lockfile


def rand_hash() -> bytes32:
    return bytes32.random()


def make_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute("CREATE TABLE database_version(version int)")
    conn.execute("INSERT INTO database_version VALUES (?)", (version,))
    conn.commit()


def make_peak(conn: sqlite3.Connection, peak_hash: bytes32) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS current_peak(key int PRIMARY KEY, hash blob)")
    conn.execute("INSERT OR REPLACE INTO current_peak VALUES(?, ?)", (0, peak_hash))
    conn.commit()


def make_block_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS full_blocks("
        "header_hash blob PRIMARY KEY,"
        "prev_hash blob,"
        "height bigint,"
        "sub_epoch_summary blob,"
        "is_fully_compactified tinyint,"
        "in_main_chain tinyint,"
        "block blob,"
        "block_record blob)"
    )


def make_coin_record_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS coin_record("
        "coin_name blob PRIMARY KEY,"
        "confirmed_index bigint,"
        "spent_index bigint,"
        "coinbase int,"
        "puzzle_hash blob,"
        "coin_parent blob,"
        "amount blob)"
    )


def make_hints_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS hints(coin_id blob, hint blob)")


def make_sub_epoch_segments_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sub_epoch_segments_v3(ses_block_hash blob PRIMARY KEY,challenge_segments blob)"
    )


def add_coin_record(
    conn: sqlite3.Connection,
    coin_name: bytes32,
    confirmed_index: int,
    spent_index: int,
    coinbase: int,
    puzzle_hash: bytes32,
    coin_parent: bytes32,
    amount: int,
) -> None:
    conn.execute(
        "INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?)",
        (coin_name, confirmed_index, spent_index, coinbase, puzzle_hash, coin_parent, amount.to_bytes(8, "big")),
    )


def add_hint(conn: sqlite3.Connection, coin_id: bytes32, hint: bytes32) -> None:
    conn.execute("INSERT INTO hints VALUES(?, ?)", (coin_id, hint))


def add_sub_epoch_segment(conn: sqlite3.Connection, ses_block_hash: bytes32) -> None:
    conn.execute("INSERT INTO sub_epoch_segments_v3 VALUES(?, ?)", (ses_block_hash, b"segment_data"))


def add_block(
    conn: sqlite3.Connection, header_hash: bytes32, prev_hash: bytes32, height: int, in_main_chain: bool
) -> None:
    conn.execute(
        "INSERT INTO full_blocks VALUES(?, ?, ?, NULL, 0, ?, NULL, NULL)",
        (
            header_hash,
            prev_hash,
            height,
            int(in_main_chain),
        ),
    )


def get_block_count(conn: sqlite3.Connection) -> int:
    with closing(conn.execute("SELECT COUNT(*) FROM full_blocks")) as cursor:
        return int(cursor.fetchone()[0])


def get_max_height(conn: sqlite3.Connection) -> int:
    with closing(conn.execute("SELECT MAX(height) FROM full_blocks")) as cursor:
        return int(cursor.fetchone()[0])


def get_peak_height(conn: sqlite3.Connection) -> int:
    with closing(conn.execute("SELECT hash FROM current_peak WHERE key = 0")) as cursor:
        peak_hash = cursor.fetchone()[0]
    with closing(conn.execute("SELECT height FROM full_blocks WHERE header_hash = ?", (peak_hash,))) as cursor:
        return int(cursor.fetchone()[0])


def create_test_db(db_file: Path, peak_height: int, orphan_rate: int = 4) -> dict[int, bytes32]:
    """
    Create a test database with blocks from height 0 to peak_height.
    Every `orphan_rate` blocks, add an orphan block at that height.
    Returns a dict mapping height to header_hash for main chain blocks.
    """
    height_to_hash: dict[int, bytes32] = {}

    with closing(sqlite3.connect(db_file)) as conn:
        make_version(conn, 2)
        make_block_table(conn)

        prev = rand_hash()  # genesis prev hash
        for height in range(peak_height + 1):
            header_hash = rand_hash()
            add_block(conn, header_hash, prev, height, True)
            height_to_hash[height] = header_hash
            if orphan_rate > 0 and height % orphan_rate == 0 and height > 0:
                # Insert an orphan block at this height
                add_block(conn, rand_hash(), prev, height, False)
            prev = header_hash

        make_peak(conn, height_to_hash[peak_height])
        conn.commit()

    return height_to_hash


class TestDbPrune:
    def test_prune_basic(self) -> None:
        """Test basic pruning removes blocks from peak."""
        with TempFile() as db_file:
            peak_height = 1000
            blocks_back = 300
            create_test_db(db_file, peak_height, orphan_rate=0)

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                new_peak_height = peak_height - blocks_back
                # Should have blocks from 0 to new_peak_height
                assert get_block_count(conn) == new_peak_height + 1
                assert get_max_height(conn) == new_peak_height
                # Peak should be updated
                assert get_peak_height(conn) == new_peak_height

    def test_prune_with_orphans(self) -> None:
        """Test pruning removes both main chain and orphan blocks above cutoff."""
        with TempFile() as db_file:
            peak_height = 1000
            blocks_back = 300
            orphan_rate = 4
            create_test_db(db_file, peak_height, orphan_rate=orphan_rate)

            with closing(sqlite3.connect(db_file)) as conn:
                initial_count = get_block_count(conn)
                # Main chain: 1001 blocks (0-1000)
                # Orphans: 250 blocks (at heights 4, 8, 12, ..., 1000)
                assert initial_count > peak_height + 1

            prune_db(db_file, blocks_back=blocks_back)

            new_peak_height = peak_height - blocks_back
            with closing(sqlite3.connect(db_file)) as conn:
                # All blocks above new_peak_height should be gone
                with closing(
                    conn.execute("SELECT COUNT(*) FROM full_blocks WHERE height > ?", (new_peak_height,))
                ) as cursor:
                    assert cursor.fetchone()[0] == 0
                # Peak should be updated
                assert get_peak_height(conn) == new_peak_height

    def test_prune_nothing_to_prune(self) -> None:
        """Test pruning when blocks_back >= peak_height does nothing."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 200
            create_test_db(db_file, peak_height, orphan_rate=0)

            with closing(sqlite3.connect(db_file)) as conn:
                initial_count = get_block_count(conn)
                initial_peak = get_peak_height(conn)

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                # Nothing should be deleted
                assert get_block_count(conn) == initial_count
                assert get_peak_height(conn) == initial_peak

    def test_prune_blocks_back_greater_than_peak(self) -> None:
        """Test pruning when blocks_back is greater than peak_height does nothing."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 101  # Greater than peak_height, can't prune below genesis
            create_test_db(db_file, peak_height, orphan_rate=0)

            with closing(sqlite3.connect(db_file)) as conn:
                initial_count = get_block_count(conn)

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                assert get_block_count(conn) == initial_count

    def test_prune_small_chain(self) -> None:
        """Test pruning a small chain with default blocks_back."""
        with TempFile() as db_file:
            peak_height = 50
            blocks_back = 300  # Default
            create_test_db(db_file, peak_height, orphan_rate=0)

            with closing(sqlite3.connect(db_file)) as conn:
                initial_count = get_block_count(conn)

            # Should not prune anything since peak_height < blocks_back
            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                assert get_block_count(conn) == initial_count

    def test_prune_aggressive(self) -> None:
        """Test aggressive pruning with small blocks_back."""
        with TempFile() as db_file:
            peak_height = 1000
            blocks_back = 10
            create_test_db(db_file, peak_height, orphan_rate=0)

            prune_db(db_file, blocks_back=blocks_back)

            new_peak_height = peak_height - blocks_back
            with closing(sqlite3.connect(db_file)) as conn:
                # Should have blocks from 0 to new_peak_height
                assert get_block_count(conn) == new_peak_height + 1
                assert get_max_height(conn) == new_peak_height
                assert get_peak_height(conn) == new_peak_height

    def test_prune_updates_peak(self) -> None:
        """Test that pruning updates the current_peak correctly."""
        with TempFile() as db_file:
            peak_height = 500
            blocks_back = 100
            height_to_hash = create_test_db(db_file, peak_height, orphan_rate=0)

            prune_db(db_file, blocks_back=blocks_back)

            new_peak_height = peak_height - blocks_back
            with closing(sqlite3.connect(db_file)) as conn:
                # Peak should be updated to the block at new_peak_height
                with closing(conn.execute("SELECT hash FROM current_peak WHERE key = 0")) as cursor:
                    new_peak_hash = bytes32(cursor.fetchone()[0])
                assert new_peak_hash == height_to_hash[new_peak_height]

                # Old peak block should be gone
                with closing(
                    conn.execute(
                        "SELECT COUNT(*) FROM full_blocks WHERE header_hash = ?", (height_to_hash[peak_height],)
                    )
                ) as cursor:
                    assert cursor.fetchone()[0] == 0


class TestDbPruneErrors:
    def test_prune_negative_blocks_back(self) -> None:
        """Test pruning with negative blocks_back raises error."""
        with TempFile() as db_file:
            create_test_db(db_file, peak_height=100, orphan_rate=0)

            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=-5)
            assert "blocks_back must be a non-negative integer" in str(excinfo.value)
            assert "-5" in str(excinfo.value)

    def test_prune_missing_file(self) -> None:
        """Test pruning non-existent database raises error."""
        with pytest.raises(RuntimeError) as excinfo:
            prune_db(Path("/nonexistent/path/to/db.sqlite"), blocks_back=300)
        assert "Database file does not exist" in str(excinfo.value)

    def test_prune_wrong_version(self) -> None:
        """Test pruning database with wrong version raises error."""
        with TempFile() as db_file:
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 1)

            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=300, skip_integrity_check=True)
            assert "Database has the wrong version (1 expected 2)" in str(excinfo.value)

    def test_prune_version_3(self) -> None:
        """Test pruning database with future version raises error."""
        with TempFile() as db_file:
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 3)

            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=300, skip_integrity_check=True)
            assert "Database has the wrong version (3 expected 2)" in str(excinfo.value)

    def test_prune_missing_version_table(self) -> None:
        """Test pruning database without version table raises error."""
        with TempFile() as db_file:
            with closing(sqlite3.connect(db_file)) as conn:
                make_block_table(conn)
                conn.commit()

            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=300)
            assert "Database is missing version table" in str(excinfo.value)

    def test_prune_missing_peak_table(self) -> None:
        """Test pruning database without peak table raises error."""
        with TempFile() as db_file:
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)
                conn.commit()

            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=300)
            assert "Database is missing current_peak table" in str(excinfo.value)

    def test_prune_missing_peak_block(self) -> None:
        """Test pruning database with missing peak block raises error."""
        with TempFile() as db_file:
            fake_peak = rand_hash()
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)
                make_peak(conn, fake_peak)
                conn.commit()

            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=300)
            assert "Database is missing the peak block" in str(excinfo.value)

    def test_prune_empty_peak(self) -> None:
        """Test pruning database with empty peak raises error."""
        with TempFile() as db_file:
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)
                conn.execute("CREATE TABLE IF NOT EXISTS current_peak(key int PRIMARY KEY, hash blob)")
                conn.commit()

            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=300)
            assert "Database is missing current_peak" in str(excinfo.value)


class TestDbPruneSingleTransaction:
    """Tests for single-transaction behavior and rollback on error."""

    def test_prune_rollback_on_commit_failure(self) -> None:
        """Test that prune_db rolls back and leaves DB unchanged when commit fails."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 30
            create_test_db(db_file, peak_height, orphan_rate=0)

            original_connect = sqlite3.connect

            class CommitRaisesWrapper:
                """Wraps a real connection but commit() raises to simulate failure."""

                def __init__(self, path: str | Path) -> None:
                    self._conn = original_connect(path)

                def commit(self) -> None:
                    raise sqlite3.OperationalError("simulated disk full")

                def __getattr__(self, name: str) -> object:
                    return getattr(self._conn, name)

            def connect_commit_raises(path: str | Path) -> CommitRaisesWrapper:
                return CommitRaisesWrapper(path)

            with patch("chia.cmds.db_prune_func.sqlite3.connect", side_effect=connect_commit_raises):
                with pytest.raises(RuntimeError) as excinfo:
                    prune_db(db_file, blocks_back=blocks_back)
                assert "Prune failed" in str(excinfo.value)
                assert "simulated disk full" in str(excinfo.value)

            # Database should be unchanged (transaction rolled back)
            with closing(sqlite3.connect(db_file)) as conn:
                assert get_peak_height(conn) == peak_height
                assert get_block_count(conn) == peak_height + 1

    def test_prune_shows_all_step_messages(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that prune prints step messages (UI step 1) in order."""
        with TempFile() as db_file:
            peak_height = 50
            blocks_back = 20
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)
                make_coin_record_table(conn)
                make_hints_table(conn)
                make_sub_epoch_segments_table(conn)
                prev = rand_hash()
                height_to_hash: dict[int, bytes32] = {}
                for height in range(peak_height + 1):
                    header_hash = rand_hash()
                    add_block(conn, header_hash, prev, height, True)
                    height_to_hash[height] = header_hash
                    prev = header_hash
                make_peak(conn, height_to_hash[peak_height])
                conn.commit()

            prune_db(db_file, blocks_back=blocks_back)

            out = capsys.readouterr().out
            assert "Updating peak..." in out
            assert "Deleting hints..." in out
            assert "Deleting coin records..." in out
            assert "Resetting spent coin records..." in out
            assert "Deleting blocks..." in out
            assert "Cleaning up sub-epoch segments..." in out
            assert "Pruning complete" in out

    def test_prune_integrity_check_failure(self) -> None:
        """Test that prune_db raises when full PRAGMA integrity_check returns non-ok."""
        with TempFile() as db_file:
            create_test_db(db_file, peak_height=100, orphan_rate=0)
            original_connect = sqlite3.connect

            class IntegrityFailCursor:
                def fetchone(self) -> tuple[str, ...]:
                    return ("corrupt",)

                def close(self) -> None:
                    pass

            class IntegrityFailWrapper:
                def __init__(self, path: str | Path) -> None:
                    self._conn = original_connect(path)

                def execute(
                    self,
                    sql: str,
                    parameters: Sequence[Any] | Mapping[str, Any] = (),
                    *args: Any,
                    **kwargs: Any,
                ) -> IntegrityFailCursor | object:
                    if sql == "PRAGMA integrity_check":
                        return IntegrityFailCursor()
                    return self._conn.execute(sql, parameters, *args, **kwargs)

                def __getattr__(self, name: str) -> object:
                    return getattr(self._conn, name)

            with patch(
                "chia.cmds.db_prune_func.sqlite3.connect",
                side_effect=IntegrityFailWrapper,
            ):
                with pytest.raises(RuntimeError) as excinfo:
                    prune_db(db_file, blocks_back=10, full_integrity_check=True)
                assert "Database integrity check failed" in str(excinfo.value)
                assert "corrupt" in str(excinfo.value)

    def test_prune_skip_integrity_check_succeeds(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that prune_db with skip_integrity_check=True skips check and prunes."""
        with TempFile() as db_file:
            create_test_db(db_file, peak_height=100, orphan_rate=0)
            prune_db(db_file, blocks_back=30, skip_integrity_check=True)
            out = capsys.readouterr().out
            assert "Skipping integrity check" in out
            assert "Pruning complete" in out
            with closing(sqlite3.connect(db_file)) as conn:
                assert get_peak_height(conn) == 70

    def test_prune_default_runs_sampled_check(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that default prune runs sampled integrity check (not full)."""
        with TempFile() as db_file:
            create_test_db(db_file, peak_height=100, orphan_rate=0)
            prune_db(db_file, blocks_back=10)
            out = capsys.readouterr().out
            assert "Running sampled integrity check" in out
            assert "Pruning complete" in out

    def test_prune_full_integrity_check_succeeds(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that prune_db with full_integrity_check=True runs full check and prunes."""
        with TempFile() as db_file:
            create_test_db(db_file, peak_height=100, orphan_rate=0)
            prune_db(db_file, blocks_back=20, full_integrity_check=True)
            out = capsys.readouterr().out
            assert "Running full integrity check" in out
            assert "Pruning complete" in out
            with closing(sqlite3.connect(db_file)) as conn:
                assert get_peak_height(conn) == 80

    def test_prune_sampled_integrity_check_failure_raises(self) -> None:
        """Test that when sampled integrity check raises, prune_db propagates it."""
        with TempFile() as db_file:
            create_test_db(db_file, peak_height=100, orphan_rate=0)

            def sampled_check_raises(conn: sqlite3.Connection) -> None:
                raise RuntimeError("Database integrity check failed at full_blocks: malformed")

            with patch(
                "chia.cmds.db_prune_func._run_sampled_integrity_check",
                side_effect=sampled_check_raises,
            ):
                with pytest.raises(RuntimeError) as excinfo:
                    prune_db(db_file, blocks_back=10)
                assert "Database integrity check failed" in str(excinfo.value)

    def test_prune_progress_callback_prints_dots(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that progress handler prints dots during long operations (line 149)."""
        with TempFile() as db_file:
            # Large prune so DELETE runs enough VDBE instructions to trigger progress callback
            peak_height = 8000
            blocks_back = 7000
            create_test_db(db_file, peak_height, orphan_rate=0)
            prune_db(db_file, blocks_back=blocks_back)
            out = capsys.readouterr().out
            # Progress handler prints "." every 10 callbacks (every 100k VDBE instructions)
            assert "." in out


class TestDbPruneOperationalErrorFix:
    """Tests that non-table OperationalErrors during optional steps propagate and cause rollback."""

    def test_prune_non_table_operational_error_during_hints_delete_rolls_back(self) -> None:
        """When DELETE FROM hints raises a non-table OperationalError (e.g. disk I/O), prune rolls back."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 30
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)
                make_coin_record_table(conn)
                make_hints_table(conn)
                prev = rand_hash()
                height_to_hash: dict[int, bytes32] = {}
                for height in range(peak_height + 1):
                    header_hash = rand_hash()
                    add_block(conn, header_hash, prev, height, True)
                    height_to_hash[height] = header_hash
                    prev = header_hash
                make_peak(conn, height_to_hash[peak_height])
                conn.commit()

            original_connect = sqlite3.connect

            class HintsDeleteRaisesWrapper:
                """Connection wrapper that raises OperationalError on DELETE FROM hints (non-table error)."""

                def __init__(self, path: str | Path) -> None:
                    self._conn = original_connect(path)

                def execute(
                    self,
                    sql: str,
                    parameters: Sequence[Any] | Mapping[str, Any] = (),
                    *args: Any,
                    **kwargs: Any,
                ) -> object:
                    if "DELETE FROM hints" in sql and "coin_id IN" in sql:
                        raise sqlite3.OperationalError("database is locked")
                    return self._conn.execute(sql, parameters, *args, **kwargs)

                def __getattr__(self, name: str) -> object:
                    return getattr(self._conn, name)

            with patch("chia.cmds.db_prune_func.sqlite3.connect", side_effect=HintsDeleteRaisesWrapper):
                with pytest.raises(RuntimeError) as excinfo:
                    prune_db(db_file, blocks_back=blocks_back)
                assert "Prune failed" in str(excinfo.value)
                assert "database is locked" in str(excinfo.value)

            # Database should be unchanged (transaction rolled back)
            with closing(sqlite3.connect(db_file)) as conn:
                assert get_peak_height(conn) == peak_height
                assert get_block_count(conn) == peak_height + 1

    def test_prune_no_such_table_optional_step_succeeds(self) -> None:
        """When optional table (e.g. hints) is missing, prune still succeeds (only 'no such table' ignored)."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 30
            # DB with full_blocks and current_peak but no hints/coin_record (create_test_db style)
            create_test_db(db_file, peak_height, orphan_rate=0)

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                assert get_peak_height(conn) == peak_height - blocks_back
                assert get_block_count(conn) == peak_height - blocks_back + 1


class TestDbPruneFuncErrorHandling:
    """Tests for db_prune_func error handling (lines 43-46)."""

    def test_db_prune_func_sqlite_error_wraps_as_runtime(self, tmp_path: Path) -> None:
        """Test db_prune_func wraps sqlite3.Error from prune_db as RuntimeError."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        db_path = root_path / "db"
        db_path.mkdir()
        db_file = db_path / "blockchain_v2_mainnet.sqlite"
        create_test_db(db_file, peak_height=100, orphan_rate=0)

        def prune_db_raises_sqlite(*args: object, **kwargs: object) -> None:
            raise sqlite3.OperationalError("disk full")

        with patch("chia.cmds.db_prune_func.prune_db", side_effect=prune_db_raises_sqlite):
            with pytest.raises(RuntimeError) as excinfo:
                db_prune_func(root_path, in_db_path=db_file, blocks_back=10)
            assert "Database error during prune" in str(excinfo.value)
            assert "disk full" in str(excinfo.value)

    def test_db_prune_func_generic_exception_wraps_as_runtime(self, tmp_path: Path) -> None:
        """Test db_prune_func wraps generic Exception from prune_db as RuntimeError."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        db_path = root_path / "db"
        db_path.mkdir()
        db_file = db_path / "blockchain_v2_mainnet.sqlite"
        create_test_db(db_file, peak_height=100, orphan_rate=0)

        def prune_db_raises_value_error(*args: object, **kwargs: object) -> None:
            raise ValueError("unexpected oops")

        with patch("chia.cmds.db_prune_func.prune_db", side_effect=prune_db_raises_value_error):
            with pytest.raises(RuntimeError) as excinfo:
                db_prune_func(root_path, in_db_path=db_file, blocks_back=10)
            assert "Unexpected error during prune" in str(excinfo.value)
            assert "unexpected oops" in str(excinfo.value)


class TestDbPruneFuncWithLock:
    def test_prune_full_node_running(self, tmp_path: Path) -> None:
        """Test that pruning fails when full_node is running (lock held)."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        run_path = root_path / "run"
        run_path.mkdir()

        # Create a minimal config
        config_path = root_path / "config"
        config_path.mkdir()
        config_file = config_path / "config.yaml"
        config_file.write_text(
            """
full_node:
  selected_network: mainnet
  database_path: db/blockchain_v2_mainnet.sqlite
"""
        )

        # Simulate full_node running by holding the lock
        lock_path = run_path / "chia_full_node"
        with Lockfile.create(lock_path):
            with pytest.raises(RuntimeError) as excinfo:
                db_prune_func(root_path, blocks_back=300)
            error_msg = str(excinfo.value)
            assert "Cannot prune database while full_node is running" in error_msg
            assert "Please stop the full_node service first with 'chia stop node'" in error_msg

    def test_prune_full_node_not_running(self, tmp_path: Path) -> None:
        """Test that pruning succeeds when full_node is not running."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        run_path = root_path / "run"
        run_path.mkdir()

        # Create a database file
        db_path = root_path / "db"
        db_path.mkdir()
        db_file = db_path / "blockchain_v2_mainnet.sqlite"
        create_test_db(db_file, peak_height=500, orphan_rate=0)

        # Create a minimal config pointing to the db
        config_path = root_path / "config"
        config_path.mkdir()
        config_file = config_path / "config.yaml"
        config_file.write_text(
            """
full_node:
  selected_network: mainnet
  database_path: db/blockchain_v2_mainnet.sqlite
"""
        )

        # Should succeed - no lock held
        db_prune_func(root_path, blocks_back=100)

        # Verify pruning happened - removed 100 blocks from peak
        with closing(sqlite3.connect(db_file)) as conn:
            assert get_peak_height(conn) == 400
            assert get_max_height(conn) == 400
            assert get_block_count(conn) == 401

    def test_db_prune_func_negative_blocks_back(self, tmp_path: Path) -> None:
        """Test that db_prune_func raises error for negative blocks_back."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        run_path = root_path / "run"
        run_path.mkdir()

        # Create a database file
        db_path = root_path / "db"
        db_path.mkdir()
        db_file = db_path / "blockchain_v2_mainnet.sqlite"
        create_test_db(db_file, peak_height=100, orphan_rate=0)

        # Create a minimal config pointing to the db
        config_path = root_path / "config"
        config_path.mkdir()
        config_file = config_path / "config.yaml"
        config_file.write_text(
            """
full_node:
  selected_network: mainnet
  database_path: db/blockchain_v2_mainnet.sqlite
"""
        )

        # Should raise RuntimeError for negative blocks_back
        with pytest.raises(RuntimeError) as excinfo:
            db_prune_func(root_path, blocks_back=-5)
        assert "blocks_back must be a non-negative integer" in str(excinfo.value)
        assert "-5" in str(excinfo.value)

    def test_db_prune_func_missing_database(self, tmp_path: Path) -> None:
        """Test that db_prune_func raises error for missing database from config."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        run_path = root_path / "run"
        run_path.mkdir()

        # Create a minimal config pointing to a non-existent db
        config_path = root_path / "config"
        config_path.mkdir()
        config_file = config_path / "config.yaml"
        config_file.write_text(
            """
full_node:
  selected_network: mainnet
  database_path: db/blockchain_v2_mainnet.sqlite
"""
        )

        # Should raise RuntimeError for missing database
        with pytest.raises(RuntimeError) as excinfo:
            db_prune_func(root_path, blocks_back=100)
        assert "Database file does not exist" in str(excinfo.value)


class TestDbPruneBlockCounts:
    def test_prune_counts_correct(self) -> None:
        """Test that block counts before and after pruning are correct."""
        with TempFile() as db_file:
            peak_height = 500
            blocks_back = 200
            orphan_rate = 5
            create_test_db(db_file, peak_height, orphan_rate=orphan_rate)

            with closing(sqlite3.connect(db_file)) as conn:
                # Count initial blocks
                initial_total = get_block_count(conn)
                with closing(conn.execute("SELECT COUNT(*) FROM full_blocks WHERE in_main_chain = 1")) as cursor:
                    initial_main = cursor.fetchone()[0]
                with closing(conn.execute("SELECT COUNT(*) FROM full_blocks WHERE in_main_chain = 0")) as cursor:
                    initial_orphans = cursor.fetchone()[0]

                # Main chain should be 501 blocks (0-500)
                assert initial_main == peak_height + 1
                # Orphans at heights 5, 10, 15, ..., 500 = 100 orphans
                assert initial_orphans == peak_height // orphan_rate
                assert initial_total == initial_main + initial_orphans

            prune_db(db_file, blocks_back=blocks_back)

            new_peak_height = peak_height - blocks_back  # 300
            with closing(sqlite3.connect(db_file)) as conn:
                # After pruning, should have blocks from 0 to 300
                # Main chain blocks from 0 to 300 = 301 blocks
                with closing(conn.execute("SELECT COUNT(*) FROM full_blocks WHERE in_main_chain = 1")) as cursor:
                    final_main = cursor.fetchone()[0]
                assert final_main == new_peak_height + 1

                # Orphans at heights 5, 10, 15, ..., 300
                # That's 300 / 5 = 60 orphans
                with closing(conn.execute("SELECT COUNT(*) FROM full_blocks WHERE in_main_chain = 0")) as cursor:
                    final_orphans = cursor.fetchone()[0]
                expected_orphans = new_peak_height // orphan_rate
                assert final_orphans == expected_orphans

    def test_prune_removes_all_above_new_peak(self) -> None:
        """Test that ALL blocks above new peak are removed."""
        with TempFile() as db_file:
            peak_height = 200
            blocks_back = 50
            create_test_db(db_file, peak_height, orphan_rate=2)

            prune_db(db_file, blocks_back=blocks_back)

            new_peak_height = peak_height - blocks_back

            with closing(sqlite3.connect(db_file)) as conn:
                # No main chain blocks above new peak
                with closing(
                    conn.execute(
                        "SELECT COUNT(*) FROM full_blocks WHERE height > ? AND in_main_chain = 1", (new_peak_height,)
                    )
                ) as cursor:
                    assert cursor.fetchone()[0] == 0

                # No orphan blocks above new peak
                with closing(
                    conn.execute(
                        "SELECT COUNT(*) FROM full_blocks WHERE height > ? AND in_main_chain = 0", (new_peak_height,)
                    )
                ) as cursor:
                    assert cursor.fetchone()[0] == 0

                # Max height should be new_peak_height
                assert get_max_height(conn) == new_peak_height


class TestDbPruneEdgeCases:
    def test_prune_almost_all(self) -> None:
        """Test pruning almost all blocks, leaving only genesis."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 100  # This means new peak = 0
            create_test_db(db_file, peak_height, orphan_rate=0)

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                # Should have only the genesis block (height 0)
                assert get_block_count(conn) == 1
                assert get_max_height(conn) == 0
                assert get_peak_height(conn) == 0

    def test_prune_to_height_one(self) -> None:
        """Test pruning to leave blocks 0 and 1."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 99  # new peak = 1
            create_test_db(db_file, peak_height, orphan_rate=0)

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                # Should have blocks 0 and 1
                assert get_block_count(conn) == 2
                assert get_max_height(conn) == 1
                assert get_peak_height(conn) == 1

    def test_prune_single_block_chain(self) -> None:
        """Test pruning a chain with only the genesis block."""
        with TempFile() as db_file:
            peak_height = 0
            create_test_db(db_file, peak_height, orphan_rate=0)

            prune_db(db_file, blocks_back=300)

            with closing(sqlite3.connect(db_file)) as conn:
                # Should still have the genesis block
                assert get_block_count(conn) == 1
                assert get_peak_height(conn) == 0

    def test_prune_successive(self) -> None:
        """Test successive prunes work correctly."""
        with TempFile() as db_file:
            peak_height = 1000
            create_test_db(db_file, peak_height, orphan_rate=0)

            # First prune: 1000 -> 900
            prune_db(db_file, blocks_back=100)
            with closing(sqlite3.connect(db_file)) as conn:
                assert get_peak_height(conn) == 900

            # Second prune: 900 -> 700
            prune_db(db_file, blocks_back=200)
            with closing(sqlite3.connect(db_file)) as conn:
                assert get_peak_height(conn) == 700

            # Third prune: 700 -> 650
            prune_db(db_file, blocks_back=50)
            with closing(sqlite3.connect(db_file)) as conn:
                assert get_peak_height(conn) == 650
                assert get_block_count(conn) == 651

    def test_prune_with_orphans_at_new_peak(self) -> None:
        """Test pruning when there are orphan blocks at the new peak height."""
        with TempFile() as db_file:
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)

                # Create a chain from height 0 to 99
                prev = rand_hash()
                height_to_hash: dict[int, bytes32] = {}
                for height in range(100):
                    header_hash = rand_hash()
                    add_block(conn, header_hash, prev, height, True)
                    height_to_hash[height] = header_hash
                    prev = header_hash

                # Add orphan blocks at heights including the new peak height (70)
                for height in [60, 70, 80, 90]:
                    add_block(conn, rand_hash(), rand_hash(), height, False)

                make_peak(conn, height_to_hash[99])
                conn.commit()

            # peak=99, blocks_back=29, new_peak=70
            prune_db(db_file, blocks_back=29)

            with closing(sqlite3.connect(db_file)) as conn:
                # Peak should now be 70
                assert get_peak_height(conn) == 70
                # Blocks at height > 70 should be gone
                with closing(conn.execute("SELECT COUNT(*) FROM full_blocks WHERE height > 70")) as cursor:
                    assert cursor.fetchone()[0] == 0
                # Orphan at height 70 should still exist
                with closing(
                    conn.execute("SELECT COUNT(*) FROM full_blocks WHERE height = 70 AND in_main_chain = 0")
                ) as cursor:
                    assert cursor.fetchone()[0] == 1


class TestDbPruneWithCoinRecords:
    """Tests for pruning with coin records, hints, and sub-epoch segments."""

    def test_prune_with_hints(self) -> None:
        """Test pruning deletes hints for coins above the new peak height."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 30
            new_peak = peak_height - blocks_back  # 70

            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)
                make_coin_record_table(conn)
                make_hints_table(conn)

                # Create blocks
                prev = rand_hash()
                height_to_hash: dict[int, bytes32] = {}
                for height in range(peak_height + 1):
                    header_hash = rand_hash()
                    add_block(conn, header_hash, prev, height, True)
                    height_to_hash[height] = header_hash
                    prev = header_hash

                make_peak(conn, height_to_hash[peak_height])

                # Add coins and hints at various heights
                # Coins below new_peak (should be preserved)
                for i in range(5):
                    coin_name = rand_hash()
                    add_coin_record(conn, coin_name, 50, 0, 1, rand_hash(), rand_hash(), 1000)
                    add_hint(conn, coin_name, rand_hash())

                # Coins above new_peak (should be deleted along with their hints)
                coins_above: list[bytes32] = []
                for i in range(10):
                    coin_name = rand_hash()
                    coins_above.append(coin_name)
                    add_coin_record(conn, coin_name, 80, 0, 1, rand_hash(), rand_hash(), 1000)
                    add_hint(conn, coin_name, rand_hash())

                conn.commit()

                # Verify initial state
                with closing(conn.execute("SELECT COUNT(*) FROM hints")) as cursor:
                    assert cursor.fetchone()[0] == 15

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                # Hints for coins above new_peak should be deleted
                with closing(conn.execute("SELECT COUNT(*) FROM hints")) as cursor:
                    assert cursor.fetchone()[0] == 5
                # Coins above new_peak should be deleted
                with closing(
                    conn.execute("SELECT COUNT(*) FROM coin_record WHERE confirmed_index > ?", (new_peak,))
                ) as cursor:
                    assert cursor.fetchone()[0] == 0

    def test_prune_resets_spent_coins(self) -> None:
        """Test pruning resets spent_index for coins spent above the new peak height."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 30
            # new_peak will be 70

            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)
                make_coin_record_table(conn)

                # Create blocks
                prev = rand_hash()
                height_to_hash: dict[int, bytes32] = {}
                for height in range(peak_height + 1):
                    header_hash = rand_hash()
                    add_block(conn, header_hash, prev, height, True)
                    height_to_hash[height] = header_hash
                    prev = header_hash

                make_peak(conn, height_to_hash[peak_height])

                # Add coins that were spent at height > new_peak (should have spent_index reset)
                spent_coins: list[bytes32] = []
                for i in range(5):
                    coin_name = rand_hash()
                    spent_coins.append(coin_name)
                    # Confirmed at height 50, spent at height 80 (above new_peak); coinbase=1
                    add_coin_record(conn, coin_name, 50, 80, 1, rand_hash(), rand_hash(), 1000)
                # Non-coinbase coin spent above new_peak (exercises reset for coinbase=0)
                non_coinbase_spent_above = rand_hash()
                spent_coins.append(non_coinbase_spent_above)
                add_coin_record(conn, non_coinbase_spent_above, 50, 80, 0, rand_hash(), rand_hash(), 1000)

                # Add coins spent below new_peak (should remain spent)
                for i in range(3):
                    coin_name = rand_hash()
                    add_coin_record(conn, coin_name, 30, 60, 1, rand_hash(), rand_hash(), 1000)

                conn.commit()

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                # Coins spent above new_peak should have spent_index reset to 0
                for coin_name in spent_coins:
                    with closing(
                        conn.execute("SELECT spent_index FROM coin_record WHERE coin_name = ?", (coin_name,))
                    ) as cursor:
                        row = cursor.fetchone()
                        assert row is not None
                        assert row[0] == 0, f"Expected spent_index=0, got {row[0]}"

                # Coins spent below new_peak should remain spent
                with closing(conn.execute("SELECT COUNT(*) FROM coin_record WHERE spent_index = 60")) as cursor:
                    assert cursor.fetchone()[0] == 3

    def test_prune_with_sub_epoch_segments(self) -> None:
        """Test pruning cleans up orphaned sub_epoch_segments_v3 entries."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 30
            # new_peak will be 70

            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)
                make_sub_epoch_segments_table(conn)

                # Create blocks
                prev = rand_hash()
                height_to_hash: dict[int, bytes32] = {}
                for height in range(peak_height + 1):
                    header_hash = rand_hash()
                    add_block(conn, header_hash, prev, height, True)
                    height_to_hash[height] = header_hash
                    prev = header_hash

                make_peak(conn, height_to_hash[peak_height])

                # Add sub_epoch_segments for blocks that will remain
                for height in [10, 30, 50, 70]:
                    add_sub_epoch_segment(conn, height_to_hash[height])

                # Add sub_epoch_segments for blocks that will be deleted (orphaned)
                for height in [80, 90, 100]:
                    add_sub_epoch_segment(conn, height_to_hash[height])

                conn.commit()

                # Verify initial state
                with closing(conn.execute("SELECT COUNT(*) FROM sub_epoch_segments_v3")) as cursor:
                    assert cursor.fetchone()[0] == 7

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                # Orphaned sub_epoch_segments should be deleted
                with closing(conn.execute("SELECT COUNT(*) FROM sub_epoch_segments_v3")) as cursor:
                    assert cursor.fetchone()[0] == 4

    def test_prune_zero_blocks_back(self) -> None:
        """Test pruning with blocks_back=0 does nothing (no blocks to prune)."""
        with TempFile() as db_file:
            peak_height = 100
            create_test_db(db_file, peak_height, orphan_rate=0)

            with closing(sqlite3.connect(db_file)) as conn:
                initial_count = get_block_count(conn)
                initial_peak = get_peak_height(conn)

            prune_db(db_file, blocks_back=0)

            with closing(sqlite3.connect(db_file)) as conn:
                # Nothing should change
                assert get_block_count(conn) == initial_count
                assert get_peak_height(conn) == initial_peak


class TestDbPruneErrorCases:
    """Additional error case tests for coverage."""

    def test_prune_empty_version_row(self) -> None:
        """Test pruning database with empty version row raises error."""
        with TempFile() as db_file:
            with closing(sqlite3.connect(db_file)) as conn:
                conn.execute("CREATE TABLE database_version(version int)")
                # Don't insert any row - table exists but is empty
                conn.commit()

            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=300, skip_integrity_check=True)
            assert "Database is missing version field" in str(excinfo.value)

    def test_prune_no_main_chain_block_at_target(self) -> None:
        """Test pruning when no main chain block exists at target height."""
        with TempFile() as db_file:
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)

                # Create main chain blocks, but skip height 70 in main chain
                prev = rand_hash()
                height_to_hash: dict[int, bytes32] = {}
                for height in range(101):
                    header_hash = rand_hash()
                    # Make height 70 NOT in main chain
                    in_main_chain = height != 70
                    add_block(conn, header_hash, prev, height, in_main_chain)
                    height_to_hash[height] = header_hash
                    prev = header_hash

                make_peak(conn, height_to_hash[100])
                conn.commit()

            # Try to prune to height 70, but there's no main chain block there
            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=30)
            assert "Cannot find main chain block at height 70" in str(excinfo.value)


class TestDbPruneLargeDatabase:
    """Tests for large databases (single transaction with UI progress)."""

    def test_prune_many_blocks_shows_progress(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test pruning >1000 blocks shows step messages and completes."""
        with TempFile() as db_file:
            peak_height = 1500
            blocks_back = 1200
            create_test_db(db_file, peak_height, orphan_rate=0)

            prune_db(db_file, blocks_back=blocks_back)

            new_peak = peak_height - blocks_back
            with closing(sqlite3.connect(db_file)) as conn:
                assert get_peak_height(conn) == new_peak
                assert get_block_count(conn) == new_peak + 1
            out = capsys.readouterr().out
            assert "Updating peak..." in out
            assert "Deleting blocks..." in out
            assert "Pruning complete" in out

    def test_prune_many_coins_shows_progress(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test pruning >1000 coins shows step messages and completes."""
        with TempFile() as db_file:
            peak_height = 100
            blocks_back = 30
            new_peak = peak_height - blocks_back  # 70

            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 2)
                make_block_table(conn)
                make_coin_record_table(conn)

                # Create blocks
                prev = rand_hash()
                height_to_hash: dict[int, bytes32] = {}
                for height in range(peak_height + 1):
                    header_hash = rand_hash()
                    add_block(conn, header_hash, prev, height, True)
                    height_to_hash[height] = header_hash
                    prev = header_hash

                make_peak(conn, height_to_hash[peak_height])

                # Add >1000 coins above new_peak
                for i in range(1500):
                    coin_name = rand_hash()
                    add_coin_record(conn, coin_name, 80, 0, 1, rand_hash(), rand_hash(), 1000)

                conn.commit()

                # Verify we have the coins
                with closing(
                    conn.execute("SELECT COUNT(*) FROM coin_record WHERE confirmed_index > ?", (new_peak,))
                ) as cursor:
                    assert cursor.fetchone()[0] == 1500

            prune_db(db_file, blocks_back=blocks_back)

            with closing(sqlite3.connect(db_file)) as conn:
                # All coins above new_peak should be deleted
                with closing(
                    conn.execute("SELECT COUNT(*) FROM coin_record WHERE confirmed_index > ?", (new_peak,))
                ) as cursor:
                    assert cursor.fetchone()[0] == 0
            out = capsys.readouterr().out
            assert "Deleting coin records..." in out
            assert "Pruning complete" in out


class TestDbPruneCli:
    """Tests for the CLI command wrapper in db.py."""

    def test_cli_prune_success(self, tmp_path: Path) -> None:
        """Test CLI command successfully prunes database."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        run_path = root_path / "run"
        run_path.mkdir()

        # Create a database file
        db_path = root_path / "db"
        db_path.mkdir()
        db_file = db_path / "blockchain_v2_mainnet.sqlite"
        create_test_db(db_file, peak_height=500, orphan_rate=0)

        # Create a minimal config
        config_path = root_path / "config"
        config_path.mkdir()
        config_file = config_path / "config.yaml"
        config_file.write_text(
            """
full_node:
  selected_network: mainnet
  database_path: db/blockchain_v2_mainnet.sqlite
"""
        )

        # Set up proper ChiaCliContext
        ctx = ChiaCliContext(root_path=root_path)

        runner = CliRunner()
        result = runner.invoke(db_prune_cmd, ["100"], obj=ctx.to_click())

        assert result.exit_code == 0
        assert "Pruning complete" in result.output

        # Verify pruning happened
        with closing(sqlite3.connect(db_file)) as conn:
            assert get_peak_height(conn) == 400

    def test_cli_prune_with_db_option(self, tmp_path: Path) -> None:
        """Test CLI command with --db option to specify database path."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        run_path = root_path / "run"
        run_path.mkdir()

        # Create a database file in a custom location
        custom_db_file = tmp_path / "custom_db.sqlite"
        create_test_db(custom_db_file, peak_height=200, orphan_rate=0)

        # Create a minimal config (won't be used since we specify --db)
        config_path = root_path / "config"
        config_path.mkdir()
        config_file = config_path / "config.yaml"
        config_file.write_text(
            """
full_node:
  selected_network: mainnet
  database_path: db/blockchain_v2_mainnet.sqlite
"""
        )

        # Set up proper ChiaCliContext
        ctx = ChiaCliContext(root_path=root_path)

        runner = CliRunner()
        result = runner.invoke(db_prune_cmd, ["50", "--db", str(custom_db_file)], obj=ctx.to_click())

        assert result.exit_code == 0
        assert "Pruning complete" in result.output

        # Verify pruning happened on the custom db
        with closing(sqlite3.connect(custom_db_file)) as conn:
            assert get_peak_height(conn) == 150

    def test_cli_prune_no_integrity_check(self, tmp_path: Path) -> None:
        """Test CLI --no-integrity-check skips integrity check and prunes."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        db_path = root_path / "db"
        db_path.mkdir()
        db_file = db_path / "blockchain_v2_mainnet.sqlite"
        create_test_db(db_file, peak_height=200, orphan_rate=0)
        config_path = root_path / "config"
        config_path.mkdir()
        config_path.joinpath("config.yaml").write_text(
            "full_node:\n  selected_network: mainnet\n  database_path: db/blockchain_v2_mainnet.sqlite\n"
        )
        ctx = ChiaCliContext(root_path=root_path)
        result = CliRunner().invoke(db_prune_cmd, ["50", "--no-integrity-check"], obj=ctx.to_click())
        assert result.exit_code == 0
        assert "Skipping integrity check" in result.output
        assert "Pruning complete" in result.output
        with closing(sqlite3.connect(db_file)) as conn:
            assert get_peak_height(conn) == 150

    def test_cli_prune_full_integrity_check(self, tmp_path: Path) -> None:
        """Test CLI --full-integrity-check runs full check and prunes."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        db_path = root_path / "db"
        db_path.mkdir()
        db_file = db_path / "blockchain_v2_mainnet.sqlite"
        create_test_db(db_file, peak_height=200, orphan_rate=0)
        config_path = root_path / "config"
        config_path.mkdir()
        config_path.joinpath("config.yaml").write_text(
            "full_node:\n  selected_network: mainnet\n  database_path: db/blockchain_v2_mainnet.sqlite\n"
        )
        ctx = ChiaCliContext(root_path=root_path)
        result = CliRunner().invoke(db_prune_cmd, ["50", "--full-integrity-check"], obj=ctx.to_click())
        assert result.exit_code == 0
        assert "Running full integrity check" in result.output
        assert "Pruning complete" in result.output
        with closing(sqlite3.connect(db_file)) as conn:
            assert get_peak_height(conn) == 150

    def test_cli_prune_error_prints_failed(self, tmp_path: Path) -> None:
        """Test CLI command prints FAILED on RuntimeError."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        run_path = root_path / "run"
        run_path.mkdir()

        # Create a minimal config pointing to a non-existent db
        config_path = root_path / "config"
        config_path.mkdir()
        config_file = config_path / "config.yaml"
        config_file.write_text(
            """
full_node:
  selected_network: mainnet
  database_path: db/blockchain_v2_mainnet.sqlite
"""
        )

        # Set up proper ChiaCliContext
        ctx = ChiaCliContext(root_path=root_path)

        runner = CliRunner()
        result = runner.invoke(db_prune_cmd, ["100"], obj=ctx.to_click())

        # Should not crash, but print FAILED
        assert result.exit_code == 0  # Click doesn't set exit code for caught exceptions
        assert "FAILED" in result.output
        assert "Database file does not exist" in result.output


class TestDbCmdCoverage:
    """Tests for db.py coverage: db_cmd (line 16), upgrade/validate/backup success and FAILED."""

    def test_db_cmd_invokable(self, tmp_path: Path) -> None:
        """Test db_cmd() callback runs when group is invoked with subcommand (line 16)."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        config_path = root_path / "config"
        config_path.mkdir()
        config_path.joinpath("config.yaml").write_text(
            "full_node:\n  selected_network: mainnet\n  database_path: db/blockchain_v2_mainnet.sqlite\n"
        )
        db_path = root_path / "db"
        db_path.mkdir()
        db_file = db_path / "blockchain_v2_mainnet.sqlite"
        create_test_db(db_file, peak_height=50, orphan_rate=0)
        ctx = ChiaCliContext(root_path=root_path)
        # Invoke the group (db_cmd) with a subcommand so the group callback runs
        result = CliRunner().invoke(db_cmd, ["prune", "10"], obj=ctx.to_click())
        assert result.exit_code == 0
        assert "Pruning complete" in result.output

    def test_db_upgrade_cmd_success_path(self, tmp_path: Path) -> None:
        """Test db upgrade command success path (lines 43-49)."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        config_path = root_path / "config"
        config_path.mkdir()
        config_path.joinpath("config.yaml").write_text(
            "full_node:\n  selected_network: mainnet\n  database_path: db/blockchain_v2_mainnet.sqlite\n"
        )
        ctx = ChiaCliContext(root_path=root_path)
        with patch("chia.cmds.db.db_upgrade_func") as mock_upgrade:
            result = CliRunner().invoke(
                db_cmd, ["upgrade", "--input", "/nonexistent", "--output", "/nonexistent"], obj=ctx.to_click()
            )
            mock_upgrade.assert_called_once()
            assert result.exit_code == 0
            assert "FAILED" not in result.output

    def test_db_upgrade_cmd_prints_failed_on_runtime_error(self, tmp_path: Path) -> None:
        """Test db upgrade command prints FAILED on RuntimeError (lines 50-51)."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        config_path = root_path / "config"
        config_path.mkdir()
        config_path.joinpath("config.yaml").write_text(
            "full_node:\n  selected_network: mainnet\n  database_path: db/blockchain_v2_mainnet.sqlite\n"
        )
        ctx = ChiaCliContext(root_path=root_path)
        with patch("chia.cmds.db.db_upgrade_func", side_effect=RuntimeError("upgrade failed")):
            result = CliRunner().invoke(db_cmd, ["upgrade"], obj=ctx.to_click())
            assert result.exit_code == 0
            assert "FAILED" in result.output
            assert "upgrade failed" in result.output

    def test_db_validate_cmd_success_path(self, tmp_path: Path) -> None:
        """Test db validate command success path (lines 65-70)."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        config_path = root_path / "config"
        config_path.mkdir()
        config_path.joinpath("config.yaml").write_text(
            "full_node:\n  selected_network: mainnet\n  database_path: db/blockchain_v2_mainnet.sqlite\n"
        )
        db_file = root_path / "db" / "blockchain_v2_mainnet.sqlite"
        db_file.parent.mkdir()
        create_test_db(db_file, peak_height=10, orphan_rate=0)
        ctx = ChiaCliContext(root_path=root_path)
        with patch("chia.cmds.db.db_validate_func") as mock_validate:
            result = CliRunner().invoke(db_cmd, ["validate", "--db", str(db_file)], obj=ctx.to_click())
            mock_validate.assert_called_once()
            assert result.exit_code == 0
            assert "FAILED" not in result.output

    def test_db_validate_cmd_prints_failed_on_runtime_error(self, tmp_path: Path) -> None:
        """Test db validate command prints FAILED on RuntimeError (lines 71-72)."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        config_path = root_path / "config"
        config_path.mkdir()
        config_path.joinpath("config.yaml").write_text(
            "full_node:\n  selected_network: mainnet\n  database_path: db/blockchain_v2_mainnet.sqlite\n"
        )
        ctx = ChiaCliContext(root_path=root_path)
        with patch("chia.cmds.db.db_validate_func", side_effect=RuntimeError("validate failed")):
            result = CliRunner().invoke(db_cmd, ["validate"], obj=ctx.to_click())
            assert result.exit_code == 0
            assert "FAILED" in result.output
            assert "validate failed" in result.output

    def test_db_backup_cmd_success_path(self, tmp_path: Path) -> None:
        """Test db backup command success path (lines 80-85)."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        config_path = root_path / "config"
        config_path.mkdir()
        config_path.joinpath("config.yaml").write_text(
            "full_node:\n  selected_network: mainnet\n  database_path: db/blockchain_v2_mainnet.sqlite\n"
        )
        db_path = root_path / "db"
        db_path.mkdir()
        db_file = db_path / "blockchain_v2_mainnet.sqlite"
        create_test_db(db_file, peak_height=10, orphan_rate=0)
        backup_file = tmp_path / "backup.sqlite"
        ctx = ChiaCliContext(root_path=root_path)
        result = CliRunner().invoke(db_cmd, ["backup", "--backup_file", str(backup_file)], obj=ctx.to_click())
        assert result.exit_code == 0
        assert "FAILED" not in result.output
        assert backup_file.exists()

    def test_db_backup_cmd_prints_failed_on_runtime_error(self, tmp_path: Path) -> None:
        """Test db backup command prints FAILED on RuntimeError (lines 86-87)."""
        root_path = tmp_path / "chia_root"
        root_path.mkdir()
        (root_path / "run").mkdir()
        config_path = root_path / "config"
        config_path.mkdir()
        config_path.joinpath("config.yaml").write_text(
            "full_node:\n  selected_network: mainnet\n  database_path: db/blockchain_v2_mainnet.sqlite\n"
        )
        ctx = ChiaCliContext(root_path=root_path)
        with patch("chia.cmds.db.db_backup_func", side_effect=RuntimeError("backup failed")):
            result = CliRunner().invoke(db_cmd, ["backup"], obj=ctx.to_click())
            assert result.exit_code == 0
            assert "FAILED" in result.output
            assert "backup failed" in result.output
