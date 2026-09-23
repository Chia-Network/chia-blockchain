from __future__ import annotations

import importlib.util
import random
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import click
import pytest
from click.testing import CliRunner

TOOL_PATH = Path(__file__).resolve().parents[3] / "tools" / "fill_coin_records.py"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fill_coin_records", TOOL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _create_coin_record_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE coin_record("
        "coin_name blob PRIMARY KEY,"
        " confirmed_index bigint,"
        " spent_index bigint,"
        " coinbase int,"
        " puzzle_hash blob,"
        " coin_parent blob,"
        " amount blob,"
        " timestamp bigint)"
    )
    conn.execute("CREATE INDEX coin_confirmed_index on coin_record(confirmed_index)")
    conn.execute("CREATE INDEX coin_spent_index on coin_record(spent_index)")
    conn.execute("CREATE INDEX coin_puzzle_hash on coin_record(puzzle_hash)")
    conn.execute("CREATE INDEX coin_parent_index on coin_record(coin_parent)")
    conn.commit()


def test_fill_coin_records_inserts_rows(tmp_path: Path) -> None:
    tool = _load_tool()
    db_path = tmp_path / "blockchain.sqlite"
    conn = sqlite3.connect(db_path)
    _create_coin_record_table(conn)

    stats = tool.fill_coin_records(
        conn,
        1_000,
        batch_size=250,
        max_height=100,
        spent_fraction=0.25,
        drop_indexes=True,
        rng=random.Random(1),
        progress=False,
        count_rows=True,
    )
    assert stats.inserted == 1_000
    assert stats.before_count == 0
    assert stats.after_count == 1_000

    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'coin_record' AND sql IS NOT NULL"
        )
    }
    assert indexes == {
        "coin_confirmed_index",
        "coin_spent_index",
        "coin_puzzle_hash",
        "coin_parent_index",
    }

    spent = conn.execute("SELECT COUNT(*) FROM coin_record WHERE spent_index > 0").fetchone()[0]
    assert 100 <= spent <= 400
    sample = conn.execute(
        "SELECT length(coin_name), length(puzzle_hash), length(coin_parent), length(amount) FROM coin_record LIMIT 1"
    ).fetchone()
    assert sample == (32, 32, 32, 8)
    heights = [
        row[0]
        for row in conn.execute("SELECT confirmed_index FROM coin_record ORDER BY confirmed_index")
    ]
    assert heights == list(range(101, 1101))
    conn.close()


def test_fill_coin_records_cli(tmp_path: Path) -> None:
    tool = _load_tool()
    db_path = tmp_path / "blockchain.sqlite"
    conn = sqlite3.connect(db_path)
    _create_coin_record_table(conn)
    conn.close()

    result = CliRunner().invoke(
        tool.main,
        ["--db", str(db_path), "--count", "500", "--batch-size", "100", "--seed", "2"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "inserted 500" in result.output
    assert "rebuilt indexes" not in result.output

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM coin_record").fetchone()[0] == 500
    indexes_after_cli = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'coin_record' AND sql IS NOT NULL"
        )
    }
    assert indexes_after_cli == {
        "coin_confirmed_index",
        "coin_spent_index",
        "coin_puzzle_hash",
        "coin_parent_index",
    }
    conn.close()


def test_repeat_seed_reports_replay(tmp_path: Path) -> None:
    tool = _load_tool()
    conn = sqlite3.connect(tmp_path / "blockchain.sqlite")
    _create_coin_record_table(conn)
    kwargs = dict(batch_size=100, max_height=100, spent_fraction=0.0, drop_indexes=False, progress=False)

    first = tool.fill_coin_records(conn, 200, rng=random.Random(7), **kwargs)
    assert (first.inserted, first.skipped) == (200, 0)

    # coin_name is the primary key, so replaying the same seed regenerates rows
    # that are already there instead of raising IntegrityError.
    with pytest.raises(click.ClickException, match="use a different --seed"):
        tool.fill_coin_records(conn, 200, rng=random.Random(7), **kwargs)

    fresh = tool.fill_coin_records(conn, 200, rng=random.Random(8), **kwargs)
    assert fresh.inserted == 200
    assert conn.execute("SELECT COUNT(*) FROM coin_record").fetchone()[0] == 400
    conn.close()


def test_cli_defaults_to_a_random_seed(tmp_path: Path) -> None:
    tool = _load_tool()
    db_path = tmp_path / "blockchain.sqlite"
    conn = sqlite3.connect(db_path)
    _create_coin_record_table(conn)
    conn.close()

    args = ["--db", str(db_path), "--count", "100", "--batch-size", "50"]
    for _ in range(2):
        result = CliRunner().invoke(tool.main, args, catch_exceptions=False)
        assert result.exit_code == 0

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM coin_record").fetchone()[0] == 200
    conn.close()


def test_max_confirmed_index_rejects_non_integer(tmp_path: Path) -> None:
    tool = _load_tool()
    conn = sqlite3.connect(tmp_path / "blockchain.sqlite")
    _create_coin_record_table(conn)
    # A corrupt coin_confirmed_index makes MAX(confirmed_index) answer with a
    # payload from another column; a bare int() on that raises ValueError.
    conn.execute(
        "INSERT INTO coin_record VALUES(?, ?, 0, 0, ?, ?, ?, 0)",
        (b"\x01" * 32, b"\x94" * 32, b"\x02" * 32, b"\x03" * 32, b"\x04" * 8),
    )
    conn.commit()

    with pytest.raises(click.ClickException, match="coin_confirmed_index index on this database is corrupt"):
        tool.max_confirmed_index(conn)
    conn.close()


def test_cli_rejects_db_inside_chia_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = _load_tool()
    root = tmp_path / "chia_root"
    db_path = root / "mainnet" / "db" / "blockchain_v2_mainnet.sqlite"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    _create_coin_record_table(conn)
    conn.close()
    monkeypatch.setenv("CHIA_ROOT", str(root))

    result = CliRunner().invoke(tool.main, ["--db", str(db_path), "--count", "10"])
    assert result.exit_code != 0
    assert "inside the Chia root" in result.output

    result = CliRunner().invoke(
        tool.main, ["--db", str(db_path), "--count", "10", "--force"], catch_exceptions=False
    )
    assert result.exit_code == 0
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM coin_record").fetchone()[0] == 10
    conn.close()
