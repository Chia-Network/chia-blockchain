from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from chia_rs.sized_bytes import bytes32
from click.testing import CliRunner

from chia._tests.util.temp_file import TempFile
from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.db import db_prune_cmd
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
                prune_db(db_file, blocks_back=300)
            assert "Database has the wrong version (1 expected 2)" in str(excinfo.value)

    def test_prune_version_3(self) -> None:
        """Test pruning database with future version raises error."""
        with TempFile() as db_file:
            with closing(sqlite3.connect(db_file)) as conn:
                make_version(conn, 3)

            with pytest.raises(RuntimeError) as excinfo:
                prune_db(db_file, blocks_back=300)
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
            assert "Cannot prune database while full_node is running" in str(excinfo.value)

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
