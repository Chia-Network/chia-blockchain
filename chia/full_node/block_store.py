from __future__ import annotations

import dataclasses
import logging
import sqlite3
from contextlib import AbstractAsyncContextManager
from typing import Optional

import aiosqlite
import typing_extensions
import zstd
from chia_rs import BlockRecord, FullBlock, SubEpochChallengeSegment, SubEpochSegments
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.full_node.full_block_utils import GeneratorBlockInfo, block_info_from_block, generator_from_block
from chia.util.batches import to_batches
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.errors import Err
from chia.util.lru_cache import LRUCache

log = logging.getLogger(__name__)


def decompress(block_bytes: bytes) -> FullBlock:
    return FullBlock.from_bytes(zstd.decompress(block_bytes))


def compress(block: FullBlock) -> bytes:
    ret: bytes = zstd.compress(bytes(block))
    return ret


def decompress_blob(block_bytes: bytes) -> bytes:
    ret: bytes = zstd.decompress(block_bytes)
    return ret


@typing_extensions.final
@dataclasses.dataclass
class BlockStore:
    block_cache: LRUCache[bytes32, FullBlock]
    db_wrapper: DBWrapper2
    ses_challenge_cache: LRUCache[bytes32, list[SubEpochChallengeSegment]]

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2, *, use_cache: bool = True) -> BlockStore:
        if db_wrapper.db_version != 2:
            raise RuntimeError(f"BlockStore does not support database schema v{db_wrapper.db_version}")

        if use_cache:
            self = cls(LRUCache(1000), db_wrapper, LRUCache(50))
        else:
            self = cls(LRUCache(0), db_wrapper, LRUCache(0))

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            log.info("DB: Creating block store tables and indexes.")
            # TODO: most data in block is duplicated in block_record. The only
            # reason for this is that our parsing of a FullBlock is so slow,
            # it's faster to store duplicate data to parse less when we just
            # need the BlockRecord. Once we fix the parsing (and data structure)
            # of FullBlock, this can use less space
            await conn.execute(
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

            # This is a single-row table containing the hash of the current
            # peak. The "key" field is there to make update statements simple
            await conn.execute("CREATE TABLE IF NOT EXISTS current_peak(key int PRIMARY KEY, hash blob)")

            # If any of these indices are altered, they should also be altered
            # in the chia/cmds/db_upgrade.py file
            log.info("DB: Creating index height")
            await conn.execute("CREATE INDEX IF NOT EXISTS height on full_blocks(height)")

            # Sub epoch segments for weight proofs
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS sub_epoch_segments_v3("
                "ses_block_hash blob PRIMARY KEY,"
                "challenge_segments blob)"
            )

            # If any of these indices are altered, they should also be altered
            # in the chia/cmds/db_upgrade.py file
            log.info("DB: Creating index is_fully_compactified")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS is_fully_compactified ON"
                " full_blocks(is_fully_compactified, in_main_chain) WHERE in_main_chain=1"
            )
            log.info("DB: Creating index main_chain")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS main_chain ON full_blocks(height, in_main_chain) WHERE in_main_chain=1"
            )

        return self

    async def rollback(self, height: int) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("UPDATE full_blocks SET in_main_chain=0 WHERE height>? AND in_main_chain=1", (height,))

    async def set_in_chain(self, header_hashes: list[tuple[bytes32]]) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            async with await conn.executemany(
                "UPDATE full_blocks SET in_main_chain=1 WHERE header_hash=?", header_hashes
            ) as cursor:
                if cursor.rowcount != len(header_hashes):
                    raise RuntimeError(f"The blockchain database is corrupt. All of {header_hashes} should exist")

    async def replace_proof(self, header_hash: bytes32, block: FullBlock) -> None:
        assert header_hash == block.header_hash

        block_bytes: bytes = compress(block)

        self.block_cache.put(header_hash, block)

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "UPDATE full_blocks SET block=?,is_fully_compactified=? WHERE header_hash=?",
                (
                    block_bytes,
                    int(block.is_fully_compactified()),
                    header_hash,
                ),
            )

    async def add_full_block(self, header_hash: bytes32, block: FullBlock, block_record: BlockRecord) -> None:
        self.block_cache.put(header_hash, block)

        ses: Optional[bytes] = (
            None if block_record.sub_epoch_summary_included is None else bytes(block_record.sub_epoch_summary_included)
        )

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO full_blocks "
                "(header_hash, "
                "prev_hash, "
                "height, "
                "sub_epoch_summary, "
                "is_fully_compactified, "
                "in_main_chain, "
                "block, "
                "block_record) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    header_hash,
                    block.prev_header_hash,
                    block.height,
                    ses,
                    int(block.is_fully_compactified()),
                    False,  # in_main_chain
                    compress(block),
                    bytes(block_record),
                ),
            )

    async def persist_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32, segments: list[SubEpochChallengeSegment]
    ) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO sub_epoch_segments_v3 VALUES(?, ?)",
                (ses_block_hash, bytes(SubEpochSegments(segments))),
            )

    async def get_sub_epoch_challenge_segments(
        self,
        ses_block_hash: bytes32,
    ) -> Optional[list[SubEpochChallengeSegment]]:
        cached: Optional[list[SubEpochChallengeSegment]] = self.ses_challenge_cache.get(ses_block_hash)
        if cached is not None:
            return cached

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT challenge_segments from sub_epoch_segments_v3 WHERE ses_block_hash=?",
                (ses_block_hash,),
            ) as cursor:
                row = await cursor.fetchone()

        if row is not None:
            challenge_segments: list[SubEpochChallengeSegment] = SubEpochSegments.from_bytes(row[0]).challenge_segments
            self.ses_challenge_cache.put(ses_block_hash, challenge_segments)
            return challenge_segments
        return None

    def transaction(self) -> AbstractAsyncContextManager[aiosqlite.Connection]:
        return self.db_wrapper.writer()

    def get_block_from_cache(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.block_cache.get(header_hash)

    def rollback_cache_block(self, header_hash: bytes32) -> None:
        try:
            self.block_cache.remove(header_hash)
        except KeyError:
            # this is best effort. When rolling back, we may not have added the
            # block to the cache yet
            pass

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        cached: Optional[FullBlock] = self.block_cache.get(header_hash)
        if cached is not None:
            return cached
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT block from full_blocks WHERE header_hash=?", (header_hash,)) as cursor:
                row = await cursor.fetchone()
        if row is not None:
            block = decompress(row[0])
            self.block_cache.put(header_hash, block)
            return block
        return None

    async def get_full_block_bytes(self, header_hash: bytes32) -> Optional[bytes]:
        cached = self.block_cache.get(header_hash)
        if cached is not None:
            return bytes(cached)
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT block from full_blocks WHERE header_hash=?", (header_hash,)) as cursor:
                row = await cursor.fetchone()
        if row is not None:
            ret: bytes = zstd.decompress(row[0])
            return ret

        return None

    async def get_full_blocks_at(self, heights: list[uint32]) -> list[FullBlock]:
        """
        Returns all blocks at the given heights, including orphans.
        """
        if len(heights) == 0:
            return []

        formatted_str = f"SELECT block from full_blocks WHERE height in ({'?,' * (len(heights) - 1)}?)"
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(formatted_str, heights) as cursor:
                ret: list[FullBlock] = []
                for row in await cursor.fetchall():
                    ret.append(decompress(row[0]))
                return ret

    async def get_block_info(self, header_hash: bytes32) -> Optional[GeneratorBlockInfo]:
        cached = self.block_cache.get(header_hash)
        if cached is not None:
            return GeneratorBlockInfo(
                cached.foliage.prev_block_hash, cached.transactions_generator, cached.transactions_generator_ref_list
            )

        formatted_str = "SELECT block, height from full_blocks WHERE header_hash=?"
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(conn, formatted_str, (header_hash,))
            if row is None:
                return None
            block_bytes = memoryview(zstd.decompress(row[0]))

            try:
                return block_info_from_block(block_bytes)
            except Exception as e:
                log.exception(f"cheap parser failed for block at height {row[1]}: {e}")
                # this is defensive, on the off-chance that
                # block_info_from_block() fails, fall back to the reliable
                # definition of parsing a block
                b = FullBlock.from_bytes(block_bytes)
                return GeneratorBlockInfo(
                    b.foliage.prev_block_hash, b.transactions_generator, b.transactions_generator_ref_list
                )

    async def get_generator(self, header_hash: bytes32) -> Optional[bytes]:
        cached = self.block_cache.get(header_hash)
        if cached is not None:
            return None if cached.transactions_generator is None else bytes(cached.transactions_generator)

        formatted_str = "SELECT block, height from full_blocks WHERE header_hash=?"
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(conn, formatted_str, (header_hash,))
            if row is None:
                return None
            block_bytes = memoryview(zstd.decompress(row[0]))

            try:
                return generator_from_block(block_bytes)
            except Exception as e:  # pragma: no cover
                log.error(f"cheap parser failed for block at height {row[1]}: {e}")
                # this is defensive, on the off-chance that
                # generator_from_block() fails, fall back to the reliable
                # definition of parsing a block
                b = FullBlock.from_bytes(block_bytes)
                return None if b.transactions_generator is None else bytes(b.transactions_generator)

    async def get_generators_at(self, heights: set[uint32]) -> dict[uint32, bytes]:
        if len(heights) == 0:
            return {}

        generators: dict[uint32, bytes] = {}
        formatted_str = (
            f"SELECT block, height from full_blocks WHERE in_main_chain=1 AND height in ({'?,' * (len(heights) - 1)}?)"
        )
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(formatted_str, list(heights)) as cursor:
                async for row in cursor:
                    block_bytes = memoryview(zstd.decompress(row[0]))

                    try:
                        gen = generator_from_block(block_bytes)
                    except Exception as e:  # pragma: no cover
                        log.error(f"cheap parser failed for block at height {row[1]}: {e}")
                        # this is defensive, on the off-chance that
                        # generator_from_block() fails, fall back to the reliable
                        # definition of parsing a block
                        b = FullBlock.from_bytes(block_bytes)
                        gen = None if b.transactions_generator is None else bytes(b.transactions_generator)
                    if gen is None:
                        raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
                    generators[uint32(row[1])] = gen

        if len(generators) != len(heights):
            raise KeyError(Err.GENERATOR_REF_HAS_NO_GENERATOR)

        return generators

    async def get_block_records_by_hash(self, header_hashes: list[bytes32]) -> list[BlockRecord]:
        """
        Returns a list of Block Records, ordered by the same order in which header_hashes are passed in.
        Throws an exception if the blocks are not present
        """

        if len(header_hashes) == 0:
            return []

        all_blocks: dict[bytes32, BlockRecord] = {}
        for batch in to_batches(header_hashes, self.db_wrapper.host_parameter_limit):
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    "SELECT header_hash,block_record FROM full_blocks "
                    f"WHERE header_hash in ({'?,' * (len(batch.entries) - 1)}?)",
                    batch.entries,
                ) as cursor:
                    for row in await cursor.fetchall():
                        block_rec = BlockRecord.from_bytes(row[1])
                        all_blocks[block_rec.header_hash] = block_rec

        ret: list[BlockRecord] = []
        for hh in header_hashes:
            if hh not in all_blocks:
                raise ValueError(f"Header hash {hh} not in the blockchain")
            ret.append(all_blocks[hh])
        return ret

    async def get_prev_hash(self, header_hash: bytes32) -> bytes32:
        """
        Returns the header hash preceeding the input header hash.
        Throws an exception if the block is not present
        """
        cached = self.block_cache.get(header_hash)
        if cached is not None:
            return cached.prev_header_hash

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT prev_hash FROM full_blocks WHERE header_hash=?",
                (header_hash,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    raise KeyError("missing block in chain")
                return bytes32(row[0])

    async def get_block_bytes_by_hash(self, header_hashes: list[bytes32]) -> list[bytes]:
        """
        Returns a list of Full Blocks block blobs, ordered by the same order in which header_hashes are passed in.
        Throws an exception if the blocks are not present
        """

        if len(header_hashes) == 0:
            return []

        assert len(header_hashes) < self.db_wrapper.host_parameter_limit
        formatted_str = (
            f"SELECT header_hash, block from full_blocks WHERE header_hash in ({'?,' * (len(header_hashes) - 1)}?)"
        )
        all_blocks: dict[bytes32, bytes] = {}
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(formatted_str, header_hashes) as cursor:
                for row in await cursor.fetchall():
                    header_hash = bytes32(row[0])
                    all_blocks[header_hash] = decompress_blob(row[1])

        ret: list[bytes] = []
        for hh in header_hashes:
            block = all_blocks.get(hh)
            if block is not None:
                ret.append(block)
            else:
                raise ValueError(f"Header hash {hh} not in the blockchain")
        return ret

    async def get_blocks_by_hash(self, header_hashes: list[bytes32]) -> list[FullBlock]:
        """
        Returns a list of Full Blocks blocks, ordered by the same order in which header_hashes are passed in.
        Throws an exception if the blocks are not present
        """

        if len(header_hashes) == 0:
            return []

        formatted_str = (
            f"SELECT header_hash, block from full_blocks WHERE header_hash in ({'?,' * (len(header_hashes) - 1)}?)"
        )
        all_blocks: dict[bytes32, FullBlock] = {}
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(formatted_str, header_hashes) as cursor:
                for row in await cursor.fetchall():
                    header_hash = bytes32(row[0])
                    full_block: FullBlock = decompress(row[1])
                    all_blocks[header_hash] = full_block
                    self.block_cache.put(header_hash, full_block)
        ret: list[FullBlock] = []
        for hh in header_hashes:
            if hh not in all_blocks:
                raise ValueError(f"Header hash {hh} not in the blockchain")
            ret.append(all_blocks[hh])
        return ret

    async def get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT block_record FROM full_blocks WHERE header_hash=?",
                (header_hash,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        block_record = BlockRecord.from_bytes(row[0])

        return block_record

    async def get_block_records_in_range(
        self,
        start: int,
        stop: int,
    ) -> dict[bytes32, BlockRecord]:
        """
        Returns a dictionary with all blocks in range between start and stop
        if present. Only blocks part of the main chain/current peak are returned.
        i.e. No orphan blocks
        """

        ret: dict[bytes32, BlockRecord] = {}
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT header_hash,block_record FROM full_blocks "
                "WHERE height >= ? AND height <= ? AND in_main_chain=1",
                (start, stop),
            ) as cursor:
                for row in await cursor.fetchall():
                    header_hash = bytes32(row[0])
                    block_record = BlockRecord.from_bytes(row[1])
                    ret[header_hash] = block_record

        return ret

    async def get_block_bytes_in_range(
        self,
        start: int,
        stop: int,
    ) -> list[bytes]:
        """
        Returns a list with all full blocks in range between start and stop
        if present. Only includes blocks in the main chain, in the current peak.
        No orphan blocks.
        """

        assert self.db_wrapper.db_version == 2
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT block FROM full_blocks WHERE height >= ? AND height <= ? AND in_main_chain=1",
                (start, stop),
            ) as cursor:
                rows: list[sqlite3.Row] = list(await cursor.fetchall())
                if len(rows) != (stop - start) + 1:
                    raise ValueError(f"Some blocks in range {start}-{stop} were not found.")
                return [decompress_blob(row[0]) for row in rows]

    async def get_peak(self) -> Optional[tuple[bytes32, uint32]]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT hash FROM current_peak WHERE key = 0") as cursor:
                peak_row = await cursor.fetchone()
        if peak_row is None:
            return None
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute("SELECT height FROM full_blocks WHERE header_hash=?", (peak_row[0],)) as cursor:
                peak_height = await cursor.fetchone()
        if peak_height is None:
            return None
        return bytes32(peak_row[0]), uint32(peak_height[0])

    async def get_block_records_close_to_peak(
        self, blocks_n: int
    ) -> tuple[dict[bytes32, BlockRecord], Optional[bytes32]]:
        """
        Returns a dictionary with all blocks that have height >= peak height - blocks_n, as well as the
        peak header hash. Only blocks that are part of the main chain/current peak are included.
        """

        peak = await self.get_peak()
        if peak is None:
            return {}, None

        ret: dict[bytes32, BlockRecord] = {}
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT header_hash, block_record FROM full_blocks WHERE height >= ? AND in_main_chain=1",
                (peak[1] - blocks_n,),
            ) as cursor:
                for row in await cursor.fetchall():
                    header_hash = bytes32(row[0])
                    ret[header_hash] = BlockRecord.from_bytes(row[1])

        return ret, peak[0]

    async def set_peak(self, header_hash: bytes32) -> None:
        # We need to be in a sqlite transaction here.
        # Note: we do not commit this to the database yet, as we need to also change the coin store

        # Note: we use the key field as 0 just to ensure all inserts replace the existing row
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("INSERT OR REPLACE INTO current_peak VALUES(?, ?)", (0, header_hash))

    async def is_fully_compactified(self, header_hash: bytes32) -> Optional[bool]:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            async with conn.execute(
                "SELECT is_fully_compactified from full_blocks WHERE header_hash=?", (header_hash,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return bool(row[0])

    async def get_random_not_compactified(self, number: int) -> list[int]:
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                f"SELECT height FROM full_blocks WHERE in_main_chain=1 AND is_fully_compactified=0 "
                f"ORDER BY RANDOM() LIMIT {number}"
            ) as cursor:
                rows = await cursor.fetchall()

        heights = [int(row[0]) for row in rows]

        return heights

    async def count_compactified_blocks(self) -> int:
        # DB V2 has an index on is_fully_compactified only for blocks in the main chain
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "select count(*) from full_blocks where is_fully_compactified=1 and in_main_chain=1"
            ) as cursor:
                row = await cursor.fetchone()

        assert row is not None

        [count] = row
        return int(count)

    async def count_uncompactified_blocks(self) -> int:
        # DB V2 has an index on is_fully_compactified only for blocks in the main chain
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "select count(*) from full_blocks where is_fully_compactified=0 and in_main_chain=1"
            ) as cursor:
                row = await cursor.fetchone()

        assert row is not None

        [count] = row
        return int(count)
