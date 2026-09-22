from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, ClassVar, cast

import typing_extensions
from chia_rs.sized_bytes import bytes32

from chia.consensus.block_store_protocol import MMRState, MMRStoreProtocol
from chia.util.db_wrapper import DBWrapper2

log = logging.getLogger(__name__)


@typing_extensions.final
@dataclasses.dataclass
class MMRStore:
    """
    Persists the canonical header MMR as a flat node array, so startup can
    hydrate the in-memory MMR directly instead of reconstructing every composite
    leaf from the coin store (two indexed queries plus Merkle hashing per block).

    `mmr_nodes` holds the flat `MerkleMountainRange.nodes` array keyed by
    position; historical MMR states are implicit prefixes of it, so no
    per-height snapshots are stored. `mmr_state` is a singleton row with the
    metadata needed to verify and hydrate the MMR.

    Only canonical appends and reorg truncations modify these tables. They are
    written with `writer_maybe_transaction` so that, when called within the
    block store's write transaction, the persisted MMR commits atomically with
    the canonical peak change. Orphan (non-canonical) blocks are never persisted
    here; if consensus later replays an orphan branch, `run_single_block()`
    reconstructs its composite leaves.
    """

    if TYPE_CHECKING:
        _protocol_check: ClassVar[MMRStoreProtocol] = cast("MMRStore", None)

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2) -> MMRStore:
        if db_wrapper.db_version != 2:
            raise RuntimeError(f"MMRStore does not support database schema v{db_wrapper.db_version}")

        self = cls(db_wrapper)

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            log.info("DB: Creating MMR store tables.")
            # The complete canonical flat-node array. Historical MMR states are
            # implicit prefixes of this table, keyed by position.
            await conn.execute("CREATE TABLE IF NOT EXISTS mmr_nodes(position INTEGER PRIMARY KEY,hash BLOB NOT NULL)")
            # Singleton metadata row (key is always 0).
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS mmr_state("
                "key INTEGER PRIMARY KEY CHECK(key = 0),"
                "aggregate_from INTEGER NOT NULL,"
                "leaf_count INTEGER NOT NULL,"
                "canonical_height INTEGER NOT NULL,"
                "canonical_header_hash BLOB NOT NULL)"
            )
        return self

    async def get_state(self) -> MMRState | None:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT aggregate_from, leaf_count, canonical_height, canonical_header_hash FROM mmr_state WHERE key=0"
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return MMRState(
            aggregate_from=row[0],
            leaf_count=row[1],
            canonical_height=row[2],
            canonical_header_hash=bytes32(row[3]),
        )

    async def get_nodes(self) -> list[bytes32]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT hash FROM mmr_nodes ORDER BY position ASC") as cursor:
                rows = await cursor.fetchall()
        return [bytes32(row[0]) for row in rows]

    async def apply_canonical_update(self, truncation: int, new_nodes: list[bytes32], state: MMRState) -> None:
        """
        Persist a canonical MMR update: drop every node at flat position >=
        `truncation`, insert `new_nodes` starting at `truncation`, and store the
        new singleton state. For a plain canonical append `truncation` is the
        prior node count (the delete is a no-op); for a reorg it is the flat-node
        count at the fork height, so the old branch's suffix is replaced by the
        new branch's nodes.

        This uses `writer_maybe_transaction` so it joins the enclosing block
        store write transaction and commits atomically with the peak change.
        """
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("DELETE FROM mmr_nodes WHERE position >= ?", (truncation,))
            await conn.executemany(
                "INSERT INTO mmr_nodes(position, hash) VALUES(?, ?)",
                [(truncation + i, node) for i, node in enumerate(new_nodes)],
            )
            await conn.execute(
                "INSERT OR REPLACE INTO mmr_state"
                "(key, aggregate_from, leaf_count, canonical_height, canonical_header_hash)"
                " VALUES(0, ?, ?, ?, ?)",
                (
                    state.aggregate_from,
                    state.leaf_count,
                    state.canonical_height,
                    state.canonical_header_hash,
                ),
            )
