#!/usr/bin/env python

"""
Bulk-insert synthetic rows into an existing ``coin_record`` table.

This is a destructive benchmark helper. Stop the full node and copy the
blockchain SQLite file before running it; a database under the Chia root is
rejected unless ``--force`` is given.

Example::

    cp ~/.chia/mainnet/db/blockchain_v2_mainnet.sqlite /tmp/bench.sqlite
    tools/py tools/fill_coin_records.py --db /tmp/bench.sqlite --count 1000

For multi-million inserts, pass ``--drop-indexes`` so secondary indexes are
rebuilt once after the load instead of updated per row. Do not use that flag
for small counts: rebuilding ``coin_record`` indexes on a full node DB dominates
the runtime.

Each run picks a random seed unless ``--seed`` is given, because ``coin_name`` is
the primary key and a repeated seed regenerates coins the previous run inserted.

Rows are inserted one transaction per ``--batch-size``, sorted by ``coin_name``,
at consecutive heights above the current tip. The WAL is checkpointed after each
commit so the reported rate includes merging into the main file; disabling that
made inserts look faster and then stalled after the last progress line.

Keeping secondary indexes is the ceiling for small loads: each row updates the
primary key plus four other B-trees, three of which are random 32-byte keys.
``--drop-indexes`` is only faster when the insert is large enough to amortize
rebuilding those indexes on the whole table (multi-million rows on a full node
DB, not 100k).
"""

from __future__ import annotations

import os
import random
import sqlite3
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import click

INSERT_SQL = "INSERT OR IGNORE INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)"
INDEX_SQL = (
    "SELECT name, sql FROM sqlite_master "
    "WHERE type = 'index' AND tbl_name = 'coin_record' AND sql IS NOT NULL"
)


@dataclass(frozen=True)
class FillStats:
    inserted: int
    skipped: int
    elapsed: float
    index_rebuild: float
    before_count: int | None
    after_count: int | None


def _require_coin_record_table(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'coin_record'"
    ).fetchone()
    if row is None:
        raise click.ClickException("database has no coin_record table")


def _table_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM coin_record").fetchone()
    assert row is not None
    return int(row[0])


def _existing_indexes(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return [(str(name), str(sql)) for name, sql in conn.execute(INDEX_SQL)]


CORRUPT_INDEX_HINT = (
    "The coin_confirmed_index index on this database is corrupt. Rebuild it with "
    "'DROP INDEX coin_confirmed_index;' (the full node recreates it on next start), "
    "or pass --max-height to skip this query."
)


def max_confirmed_index(conn: sqlite3.Connection) -> int:
    """
    Largest ``confirmed_index``, answered from ``coin_confirmed_index``.

    A damaged index shows up here either as a hard ``DatabaseError`` or as a
    value from some other column, so reject anything that is not an integer.
    """
    try:
        row = conn.execute("SELECT MAX(confirmed_index) FROM coin_record").fetchone()
    except sqlite3.DatabaseError as e:
        raise click.ClickException(f"reading MAX(confirmed_index) failed: {e}. {CORRUPT_INDEX_HINT}") from e
    if row is None or row[0] is None:
        return 0
    value = row[0]
    if not isinstance(value, int):
        raise click.ClickException(
            f"MAX(confirmed_index) returned {type(value).__name__}, not an integer. {CORRUPT_INDEX_HINT}"
        )
    return value


def _apply_fast_pragmas(
    conn: sqlite3.Connection, *, mmap_bytes: int, cache_kib: int, temp_store_memory: bool
) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    # Autocheckpoint during a batch still stalls the insert. Checkpoint PASSIVE
    # after each commit instead, so the WAL does not pile up until process exit.
    conn.execute("PRAGMA wal_autocheckpoint=0")
    if temp_store_memory:
        # An index rebuild sorts the whole table, so keep its spill files on disk
        # instead of risking an OOM kill partway through writing index pages.
        conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")
    conn.execute(f"PRAGMA cache_size={-abs(cache_kib)}")
    if mmap_bytes > 0:
        conn.execute(f"PRAGMA mmap_size={mmap_bytes}")
    conn.execute("PRAGMA busy_timeout=60000")


def _chia_root_dirs() -> list[Path]:
    roots = [Path.home() / ".chia", Path.home() / ".chia_simulator"]
    env_root = os.environ.get("CHIA_ROOT")
    if env_root:
        roots.append(Path(env_root))
    return roots


def live_root_db(db_path: Path) -> Path | None:
    """The Chia root that ``db_path`` lives under, if any."""
    resolved = db_path.resolve()
    for root in _chia_root_dirs():
        try:
            resolved.relative_to(root.expanduser().resolve())
        except (OSError, ValueError):
            continue
        return root
    return None


def generate_rows(
    count: int,
    *,
    max_height: int,
    spent_fraction: float,
    rng: random.Random,
    start_height: int | None = None,
) -> Iterator[tuple[bytes, int, int, int, bytes, bytes, bytes, int]]:
    if max_height < 1:
        raise ValueError("max_height must be >= 1")
    if not 0.0 <= spent_fraction <= 1.0:
        raise ValueError("spent_fraction must be in [0, 1]")

    for i in range(count):
        blob = rng.randbytes(104)
        # Sequential heights append to coin_confirmed_index instead of seeking
        # into the middle of a multi-gigabyte B-tree. Random heights are only
        # useful when the synthetic data must look like historical scatter.
        confirmed = rng.randint(1, max_height) if start_height is None else start_height + i
        if rng.random() < spent_fraction:
            spent = rng.randint(confirmed, max(confirmed, max_height))
        else:
            spent = 0
        yield (
            blob[0:32],
            confirmed,
            spent,
            0,
            blob[32:64],
            blob[64:96],
            blob[96:104],
            1_600_000_000 + confirmed * 19,
        )


def fill_coin_records(
    conn: sqlite3.Connection,
    count: int,
    *,
    batch_size: int,
    max_height: int,
    spent_fraction: float,
    drop_indexes: bool,
    rng: random.Random,
    progress: bool = True,
    count_rows: bool = False,
    scatter_heights: bool = False,
) -> FillStats:
    if count < 1:
        raise ValueError("count must be >= 1")
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    _require_coin_record_table(conn)
    before_count = _table_count(conn) if count_rows else None
    indexes = _existing_indexes(conn) if drop_indexes else []
    # End any implicit sqlite3 transaction so we can run one exclusive bulk write.
    conn.commit()

    if drop_indexes:
        if progress:
            print(f"dropping {len(indexes)} secondary indexes", file=sys.stderr)
        for name, _sql in indexes:
            conn.execute(f'DROP INDEX IF EXISTS "{name}"')
        conn.commit()

    inserted = 0
    skipped = 0
    start = time.monotonic()
    try:
        while inserted < count:
            n = min(batch_size, count - inserted)
            rows = list(
                generate_rows(
                    n,
                    max_height=max_height,
                    spent_fraction=spent_fraction,
                    rng=rng,
                    start_height=None if scatter_heights else max_height + 1 + inserted + skipped,
                )
            )
            # Inserting in key order walks the coin_name B-tree forward instead of
            # seeking to a random leaf per row.
            rows.sort(key=lambda row: row[0])
            batch_start = time.monotonic()
            before_changes = conn.total_changes
            # One transaction per batch. A single transaction spanning the whole
            # run grows the dirty set past the page cache, which spills to the WAL
            # and then has to read those pages back.
            conn.execute("BEGIN")
            conn.executemany(INSERT_SQL, rows)
            # coin_name is the primary key, so a collision means this RNG stream
            # already ran against this database.
            new_rows = conn.total_changes - before_changes
            if new_rows == 0:
                raise click.ClickException(
                    f"all {n:,} generated coins already exist in coin_record. This seed replays a "
                    "previous run against this database; use a different --seed."
                )
            conn.commit()
            # Fold WAL frames into the main file now. Deferring this until process
            # exit (wal_autocheckpoint=0 plus a final TRUNCATE) made insert rates
            # look high and then stalled for minutes after the last progress line.
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            inserted += new_rows
            skipped += n - new_rows
            if progress:
                now = time.monotonic()
                elapsed = now - start
                overall = inserted / elapsed if elapsed > 0 else 0.0
                batch_elapsed = now - batch_start
                # The per-batch rate is the useful number: it falls as the run
                # touches more of the B-trees than the page cache can hold.
                recent = new_rows / batch_elapsed if batch_elapsed > 0 else 0.0
                print(
                    f"inserted {inserted:,}/{count:,} ({recent:,.0f} rows/s batch, {overall:,.0f} rows/s avg)",
                    file=sys.stderr,
                )
    except BaseException:
        conn.rollback()
        raise

    insert_elapsed = time.monotonic() - start
    index_start = time.monotonic()
    if drop_indexes:
        if progress:
            print(f"rebuilding {len(indexes)} secondary indexes", file=sys.stderr)
        for _name, sql in indexes:
            conn.execute(sql)
        conn.commit()
    index_elapsed = time.monotonic() - index_start

    return FillStats(
        inserted=inserted,
        skipped=skipped,
        elapsed=insert_elapsed,
        index_rebuild=index_elapsed,
        before_count=before_count,
        after_count=_table_count(conn) if count_rows else None,
    )


@click.command()
@click.option(
    "--db",
    "db_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="path to blockchain_v2_*.sqlite (copy first; do not use a live node DB)",
)
@click.option("--count", type=int, required=True, help="number of synthetic coin_record rows to insert")
@click.option(
    "--batch-size",
    type=int,
    default=10_000,
    show_default=True,
    help="rows per transaction; keep the batch's dirty pages (roughly 5 pages per row) under --cache-mb",
)
@click.option(
    "--max-height",
    type=int,
    default=None,
    help="confirmed/spent height upper bound (default: max existing confirmed_index, or 1_000_000)",
)
@click.option(
    "--spent-fraction",
    type=float,
    default=0.0,
    show_default=True,
    help="fraction of inserted coins with spent_index > 0",
)
@click.option(
    "--seed",
    type=int,
    default=None,
    help="PRNG seed (default: random per run, printed on start; a fixed seed re-run on the "
    "same database regenerates the same coin_name values and inserts nothing)",
)
@click.option(
    "--drop-indexes",
    is_flag=True,
    default=False,
    help="drop and rebuild secondary indexes (only worth it for multi-million-row loads)",
)
@click.option(
    "--count-rows",
    is_flag=True,
    default=False,
    help="SELECT COUNT(*) before and after (slow on large coin_record tables)",
)
@click.option(
    "--scatter-heights",
    is_flag=True,
    default=False,
    help="pick confirmed_index uniformly in 1..max-height (slower: seeks into coin_confirmed_index)",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="allow writing to a database under the Chia root (normally rejected)",
)
@click.option("--cache-mb", type=int, default=1024, show_default=True, help="SQLite page cache size in MiB")
@click.option("--mmap-mb", type=int, default=0, show_default=True, help="SQLite mmap size in MiB (0 disables)")
def main(
    db_path: Path,
    count: int,
    batch_size: int,
    max_height: int | None,
    spent_fraction: float,
    seed: int | None,
    drop_indexes: bool,
    count_rows: bool,
    scatter_heights: bool,
    force: bool,
    cache_mb: int,
    mmap_mb: int,
) -> None:
    if count < 1:
        raise click.ClickException("count must be >= 1")
    if not 0.0 <= spent_fraction <= 1.0:
        raise click.ClickException("spent-fraction must be in [0, 1]")

    if seed is None:
        seed = random.SystemRandom().randrange(2**32)
    print(f"seed {seed}", file=sys.stderr)

    root = live_root_db(db_path)
    if root is not None and not force:
        raise click.ClickException(
            f"{db_path} is inside the Chia root {root}. This tool writes synthetic rows and "
            "cannot be undone; copy the database elsewhere first, or pass --force."
        )

    uri = db_path.resolve().as_uri() + "?mode=rw"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    try:
        _apply_fast_pragmas(
            conn,
            mmap_bytes=mmap_mb * 1024 * 1024,
            cache_kib=cache_mb * 1024,
            temp_store_memory=not drop_indexes,
        )
        _require_coin_record_table(conn)
        if max_height is None:
            existing_max = max_confirmed_index(conn)
            max_height = existing_max if existing_max >= 1 else 1_000_000

        stats = fill_coin_records(
            conn,
            count,
            batch_size=batch_size,
            max_height=max_height,
            spent_fraction=spent_fraction,
            drop_indexes=drop_indexes,
            rng=random.Random(seed),
            count_rows=count_rows,
            scatter_heights=scatter_heights,
        )
    finally:
        conn.close()

    print(
        f"inserted {stats.inserted:,} rows in {stats.elapsed:.2f}s "
        f"({stats.inserted / stats.elapsed:,.0f} rows/s)"
    )
    if stats.skipped:
        print(f"skipped {stats.skipped:,} rows that collided with existing coin_name values")
    if drop_indexes:
        print(f"rebuilt indexes in {stats.index_rebuild:.2f}s")
    if stats.before_count is not None and stats.after_count is not None:
        print(f"coin_record count {stats.before_count:,} -> {stats.after_count:,}")


if __name__ == "__main__":
    main()
