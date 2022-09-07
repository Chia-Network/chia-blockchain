from __future__ import annotations

import dataclasses
import logging
import sqlite3
from typing import Dict, List, Optional, Tuple, Any, Union, Sequence

import typing_extensions
import zstd

from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.weight_proof import SubEpochChallengeSegment, SubEpochSegments
from chia.util.db_wrapper import DBWrapper2, execute_fetchone
from chia.util.errors import Err
from chia.util.full_block_utils import block_info_from_block, generator_from_block
from chia.util.ints import uint32
from chia.util.lru_cache import LRUCache
from chia.util.full_block_utils import GeneratorBlockInfo

log = logging.getLogger(__name__)


@typing_extensions.final
@dataclasses.dataclass
class BlockStore:
    block_cache: LRUCache[bytes32, FullBlock]
    db_wrapper: DBWrapper2
    ses_challenge_cache: LRUCache[bytes32, List[SubEpochChallengeSegment]]

    @classmethod
    async def create(cls, db_wrapper: DBWrapper2) -> BlockStore:
        self = cls(LRUCache(1000), db_wrapper, LRUCache(50))

        async with self.db_wrapper.writer_maybe_transaction() as conn:

            log.info("DB: Creating block store tables and indexes.")
            if self.db_wrapper.db_version == 2:

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

            else:

                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS full_blocks(header_hash text PRIMARY KEY, height bigint,"
                    "  is_block tinyint, is_fully_compactified tinyint, block blob)"
                )

                # Block records
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS block_records(header_hash "
                    "text PRIMARY KEY, prev_hash text, height bigint,"
                    "block blob, sub_epoch_summary blob, is_peak tinyint, is_block tinyint)"
                )

                # Sub epoch segments for weight proofs
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS sub_epoch_segments_v3(ses_block_hash text PRIMARY KEY,"
                    "challenge_segments blob)"
                )

                # Height index so we can look up in order of height for sync purposes
                log.info("DB: Creating index full_block_height")
                await conn.execute("CREATE INDEX IF NOT EXISTS full_block_height on full_blocks(height)")
                log.info("DB: Creating index is_fully_compactified")
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS is_fully_compactified on full_blocks(is_fully_compactified)"
                )

                log.info("DB: Creating index height")
                await conn.execute("CREATE INDEX IF NOT EXISTS height on block_records(height)")

                log.info("DB: Creating index peak")
                await conn.execute("CREATE INDEX IF NOT EXISTS peak on block_records(is_peak)")

        return self

    def maybe_from_hex(self, field: Union[bytes, str]) -> bytes32:
        if self.db_wrapper.db_version == 2:
            assert isinstance(field, bytes)
            return bytes32(field)
        else:
            assert isinstance(field, str)
            return bytes32.fromhex(field)

    def maybe_to_hex(self, field: bytes) -> Any:
        if self.db_wrapper.db_version == 2:
            return field
        else:
            return field.hex()

    def compress(self, block: FullBlock) -> bytes:
        ret: bytes = zstd.compress(bytes(block))
        return ret

    def maybe_decompress(self, block_bytes: bytes) -> FullBlock:
        if self.db_wrapper.db_version == 2:
            ret: FullBlock = FullBlock.from_bytes(zstd.decompress(block_bytes))
        else:
            ret = FullBlock.from_bytes(block_bytes)
        return ret

    def maybe_decompress_blob(self, block_bytes: bytes) -> bytes:
        if self.db_wrapper.db_version == 2:
            ret: bytes = zstd.decompress(block_bytes)
            return ret
        else:
            return block_bytes

    async def rollback(self, height: int) -> None:
        if self.db_wrapper.db_version == 2:
            async with self.db_wrapper.writer_maybe_transaction() as conn:
                await conn.execute(
                    "UPDATE OR FAIL full_blocks SET in_main_chain=0 WHERE height>? AND in_main_chain=1", (height,)
                )

    async def set_in_chain(self, header_hashes: List[Tuple[bytes32]]) -> None:
        if self.db_wrapper.db_version == 2:
            async with self.db_wrapper.writer_maybe_transaction() as conn:
                await conn.executemany(
                    "UPDATE OR FAIL full_blocks SET in_main_chain=1 WHERE header_hash=?", header_hashes
                )

    async def replace_proof(self, header_hash: bytes32, block: FullBlock) -> None:

        assert header_hash == block.header_hash

        block_bytes: bytes
        if self.db_wrapper.db_version == 2:
            block_bytes = self.compress(block)
        else:
            block_bytes = bytes(block)

        self.block_cache.put(header_hash, block)

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "UPDATE full_blocks SET block=?,is_fully_compactified=? WHERE header_hash=?",
                (
                    block_bytes,
                    int(block.is_fully_compactified()),
                    self.maybe_to_hex(header_hash),
                ),
            )

    async def add_full_block(self, header_hash: bytes32, block: FullBlock, block_record: BlockRecord) -> None:
        self.block_cache.put(header_hash, block)

        if self.db_wrapper.db_version == 2:

            ses: Optional[bytes] = (
                None
                if block_record.sub_epoch_summary_included is None
                else bytes(block_record.sub_epoch_summary_included)
            )

            async with self.db_wrapper.writer_maybe_transaction() as conn:
                await conn.execute(
                    "INSERT OR IGNORE INTO full_blocks VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        header_hash,
                        block.prev_header_hash,
                        block.height,
                        ses,
                        int(block.is_fully_compactified()),
                        False,  # in_main_chain
                        self.compress(block),
                        bytes(block_record),
                    ),
                )

        else:
            async with self.db_wrapper.writer_maybe_transaction() as conn:
                await conn.execute(
                    "INSERT OR IGNORE INTO full_blocks VALUES(?, ?, ?, ?, ?)",
                    (
                        header_hash.hex(),
                        block.height,
                        int(block.is_transaction_block()),
                        int(block.is_fully_compactified()),
                        bytes(block),
                    ),
                )

                await conn.execute(
                    "INSERT OR IGNORE INTO block_records VALUES(?, ?, ?, ?,?, ?, ?)",
                    (
                        header_hash.hex(),
                        block.prev_header_hash.hex(),
                        block.height,
                        bytes(block_record),
                        None
                        if block_record.sub_epoch_summary_included is None
                        else bytes(block_record.sub_epoch_summary_included),
                        False,
                        block.is_transaction_block(),
                    ),
                )

    async def persist_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32, segments: List[SubEpochChallengeSegment]
    ) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO sub_epoch_segments_v3 VALUES(?, ?)",
                (self.maybe_to_hex(ses_block_hash), bytes(SubEpochSegments(segments))),
            )

    async def get_sub_epoch_challenge_segments(
        self,
        ses_block_hash: bytes32,
    ) -> Optional[List[SubEpochChallengeSegment]]:
        cached: Optional[List[SubEpochChallengeSegment]] = self.ses_challenge_cache.get(ses_block_hash)
        if cached is not None:
            return cached

        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT challenge_segments from sub_epoch_segments_v3 WHERE ses_block_hash=?",
                (self.maybe_to_hex(ses_block_hash),),
            ) as cursor:
                row = await cursor.fetchone()

        if row is not None:
            challenge_segments: List[SubEpochChallengeSegment] = SubEpochSegments.from_bytes(row[0]).challenge_segments
            self.ses_challenge_cache.put(ses_block_hash, challenge_segments)
            return challenge_segments
        return None

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
            log.debug(f"cache hit for block {header_hash.hex()}")
            return cached
        log.debug(f"cache miss for block {header_hash.hex()}")
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT block from full_blocks WHERE header_hash=?", (self.maybe_to_hex(header_hash),)
            ) as cursor:
                row = await cursor.fetchone()
        if row is not None:
            block = self.maybe_decompress(row[0])
            self.block_cache.put(header_hash, block)
            return block
        return None

    async def get_full_block_bytes(self, header_hash: bytes32) -> Optional[bytes]:
        cached = self.block_cache.get(header_hash)
        if cached is not None:
            log.debug(f"cache hit for block {header_hash.hex()}")
            return bytes(cached)
        log.debug(f"cache miss for block {header_hash.hex()}")
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT block from full_blocks WHERE header_hash=?", (self.maybe_to_hex(header_hash),)
            ) as cursor:
                row = await cursor.fetchone()
        if row is not None:
            if self.db_wrapper.db_version == 2:
                ret: bytes = zstd.decompress(row[0])
            else:
                ret = row[0]
            return ret

        return None

    async def get_full_blocks_at(self, heights: List[uint32]) -> List[FullBlock]:
        if len(heights) == 0:
            return []

        formatted_str = f'SELECT block from full_blocks WHERE height in ({"?," * (len(heights) - 1)}?)'
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(formatted_str, heights) as cursor:
                ret: List[FullBlock] = []
                for row in await cursor.fetchall():
                    ret.append(self.maybe_decompress(row[0]))
                return ret

    async def get_block_info(self, header_hash: bytes32) -> Optional[GeneratorBlockInfo]:

        cached = self.block_cache.get(header_hash)
        if cached is not None:
            log.debug(f"cache hit for block {header_hash.hex()}")
            return GeneratorBlockInfo(
                cached.foliage.prev_block_hash, cached.transactions_generator, cached.transactions_generator_ref_list
            )

        formatted_str = "SELECT block, height from full_blocks WHERE header_hash=?"
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(conn, formatted_str, (self.maybe_to_hex(header_hash),))
            if row is None:
                return None
            if self.db_wrapper.db_version == 2:
                block_bytes = zstd.decompress(row[0])
            else:
                block_bytes = row[0]

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

    async def get_generator(self, header_hash: bytes32) -> Optional[SerializedProgram]:

        cached = self.block_cache.get(header_hash)
        if cached is not None:
            log.debug(f"cache hit for block {header_hash.hex()}")
            return cached.transactions_generator

        formatted_str = "SELECT block, height from full_blocks WHERE header_hash=?"
        async with self.db_wrapper.reader_no_transaction() as conn:
            row = await execute_fetchone(conn, formatted_str, (self.maybe_to_hex(header_hash),))
            if row is None:
                return None
            if self.db_wrapper.db_version == 2:
                block_bytes = zstd.decompress(row[0])
            else:
                block_bytes = row[0]

            try:
                return generator_from_block(block_bytes)
            except Exception as e:
                log.error(f"cheap parser failed for block at height {row[1]}: {e}")
                # this is defensive, on the off-chance that
                # generator_from_block() fails, fall back to the reliable
                # definition of parsing a block
                b = FullBlock.from_bytes(block_bytes)
                return b.transactions_generator

    async def get_generators_at(self, heights: List[uint32]) -> List[SerializedProgram]:
        assert self.db_wrapper.db_version == 2

        if len(heights) == 0:
            return []

        generators: Dict[uint32, SerializedProgram] = {}
        formatted_str = (
            f"SELECT block, height from full_blocks "
            f'WHERE in_main_chain=1 AND height in ({"?," * (len(heights) - 1)}?)'
        )
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(formatted_str, heights) as cursor:
                async for row in cursor:
                    block_bytes = zstd.decompress(row[0])

                    try:
                        gen = generator_from_block(block_bytes)
                    except Exception as e:
                        log.error(f"cheap parser failed for block at height {row[1]}: {e}")
                        # this is defensive, on the off-chance that
                        # generator_from_block() fails, fall back to the reliable
                        # definition of parsing a block
                        b = FullBlock.from_bytes(block_bytes)
                        gen = b.transactions_generator
                    if gen is None:
                        raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
                    generators[uint32(row[1])] = gen

        return [generators[h] for h in heights]

    async def get_block_records_by_hash(self, header_hashes: List[bytes32]) -> List[BlockRecord]:
        """
        Returns a list of Block Records, ordered by the same order in which header_hashes are passed in.
        Throws an exception if the blocks are not present
        """
        if len(header_hashes) == 0:
            return []

        all_blocks: Dict[bytes32, BlockRecord] = {}
        if self.db_wrapper.db_version == 2:
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    "SELECT header_hash,block_record FROM full_blocks "
                    f'WHERE header_hash in ({"?," * (len(header_hashes) - 1)}?)',
                    header_hashes,
                ) as cursor:
                    for row in await cursor.fetchall():
                        header_hash = bytes32(row[0])
                        all_blocks[header_hash] = BlockRecord.from_bytes(row[1])
        else:
            formatted_str = f'SELECT block from block_records WHERE header_hash in ({"?," * (len(header_hashes) - 1)}?)'
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(formatted_str, [hh.hex() for hh in header_hashes]) as cursor:
                    for row in await cursor.fetchall():
                        block_rec: BlockRecord = BlockRecord.from_bytes(row[0])
                        all_blocks[block_rec.header_hash] = block_rec

        ret: List[BlockRecord] = []
        for hh in header_hashes:
            if hh not in all_blocks:
                raise ValueError(f"Header hash {hh} not in the blockchain")
            ret.append(all_blocks[hh])
        return ret

    async def get_block_bytes_by_hash(self, header_hashes: List[bytes32]) -> List[bytes]:
        """
        Returns a list of Full Blocks block blobs, ordered by the same order in which header_hashes are passed in.
        Throws an exception if the blocks are not present
        """

        if len(header_hashes) == 0:
            return []

        # sqlite on python3.7 on windows has issues with large variable substitutions
        assert len(header_hashes) < 901
        header_hashes_db: Sequence[Union[bytes32, str]]
        if self.db_wrapper.db_version == 2:
            header_hashes_db = header_hashes
        else:
            header_hashes_db = [hh.hex() for hh in header_hashes]
        formatted_str = (
            f'SELECT header_hash, block from full_blocks WHERE header_hash in ({"?," * (len(header_hashes_db) - 1)}?)'
        )
        all_blocks: Dict[bytes32, bytes] = {}
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(formatted_str, header_hashes_db) as cursor:
                for row in await cursor.fetchall():
                    header_hash = self.maybe_from_hex(row[0])
                    all_blocks[header_hash] = self.maybe_decompress_blob(row[1])

        ret: List[bytes] = []
        for hh in header_hashes:
            block = all_blocks.get(hh)
            if block is not None:
                ret.append(block)
            else:
                raise ValueError(f"Header hash {hh} not in the blockchain")
        return ret

    async def get_blocks_by_hash(self, header_hashes: List[bytes32]) -> List[FullBlock]:
        """
        Returns a list of Full Blocks blocks, ordered by the same order in which header_hashes are passed in.
        Throws an exception if the blocks are not present
        """

        if len(header_hashes) == 0:
            return []

        header_hashes_db: Sequence[Union[bytes32, str]]
        if self.db_wrapper.db_version == 2:
            header_hashes_db = header_hashes
        else:
            header_hashes_db = [hh.hex() for hh in header_hashes]
        formatted_str = (
            f'SELECT header_hash, block from full_blocks WHERE header_hash in ({"?," * (len(header_hashes_db) - 1)}?)'
        )
        all_blocks: Dict[bytes32, FullBlock] = {}
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(formatted_str, header_hashes_db) as cursor:
                for row in await cursor.fetchall():
                    header_hash = self.maybe_from_hex(row[0])
                    full_block: FullBlock = self.maybe_decompress(row[1])
                    all_blocks[header_hash] = full_block
                    self.block_cache.put(header_hash, full_block)
        ret: List[FullBlock] = []
        for hh in header_hashes:
            if hh not in all_blocks:
                raise ValueError(f"Header hash {hh} not in the blockchain")
            ret.append(all_blocks[hh])
        return ret

    async def get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:

        if self.db_wrapper.db_version == 2:

            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    "SELECT block_record FROM full_blocks WHERE header_hash=?",
                    (header_hash,),
                ) as cursor:
                    row = await cursor.fetchone()
            if row is not None:
                return BlockRecord.from_bytes(row[0])

        else:
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    "SELECT block from block_records WHERE header_hash=?",
                    (header_hash.hex(),),
                ) as cursor:
                    row = await cursor.fetchone()
            if row is not None:
                return BlockRecord.from_bytes(row[0])
        return None

    async def get_block_records_in_range(
        self,
        start: int,
        stop: int,
    ) -> Dict[bytes32, BlockRecord]:
        """
        Returns a dictionary with all blocks in range between start and stop
        if present.
        """

        ret: Dict[bytes32, BlockRecord] = {}
        if self.db_wrapper.db_version == 2:

            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    "SELECT header_hash, block_record FROM full_blocks WHERE height >= ? AND height <= ?",
                    (start, stop),
                ) as cursor:
                    for row in await cursor.fetchall():
                        header_hash = bytes32(row[0])
                        ret[header_hash] = BlockRecord.from_bytes(row[1])

        else:

            formatted_str = f"SELECT header_hash, block from block_records WHERE height >= {start} and height <= {stop}"

            async with self.db_wrapper.reader_no_transaction() as conn:
                async with await conn.execute(formatted_str) as cursor:
                    for row in await cursor.fetchall():
                        header_hash = self.maybe_from_hex(row[0])
                        ret[header_hash] = BlockRecord.from_bytes(row[1])

        return ret

    async def get_block_bytes_in_range(
        self,
        start: int,
        stop: int,
    ) -> List[bytes]:
        """
        Returns a list with all full blocks in range between start and stop
        if present.
        """

        maybe_decompress_blob = self.maybe_decompress_blob
        assert self.db_wrapper.db_version == 2
        async with self.db_wrapper.reader_no_transaction() as conn:
            async with conn.execute(
                "SELECT block FROM full_blocks WHERE height >= ? AND height <= ? and in_main_chain=1",
                (start, stop),
            ) as cursor:
                rows: List[sqlite3.Row] = list(await cursor.fetchall())
                if len(rows) != (stop - start) + 1:
                    raise ValueError(f"Some blocks in range {start}-{stop} were not found.")
                return [maybe_decompress_blob(row[0]) for row in rows]

    async def get_peak(self) -> Optional[Tuple[bytes32, uint32]]:

        if self.db_wrapper.db_version == 2:
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
        else:
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute("SELECT header_hash, height from block_records WHERE is_peak = 1") as cursor:
                    peak_row = await cursor.fetchone()
            if peak_row is None:
                return None
            return bytes32(bytes.fromhex(peak_row[0])), uint32(peak_row[1])

    async def get_block_records_close_to_peak(
        self, blocks_n: int
    ) -> Tuple[Dict[bytes32, BlockRecord], Optional[bytes32]]:
        """
        Returns a dictionary with all blocks that have height >= peak height - blocks_n, as well as the
        peak header hash.
        """

        peak = await self.get_peak()
        if peak is None:
            return {}, None

        ret: Dict[bytes32, BlockRecord] = {}
        if self.db_wrapper.db_version == 2:

            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    "SELECT header_hash, block_record FROM full_blocks WHERE height >= ?",
                    (peak[1] - blocks_n,),
                ) as cursor:
                    for row in await cursor.fetchall():
                        header_hash = bytes32(row[0])
                        ret[header_hash] = BlockRecord.from_bytes(row[1])

        else:
            formatted_str = f"SELECT header_hash, block  from block_records WHERE height >= {peak[1] - blocks_n}"
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(formatted_str) as cursor:
                    for row in await cursor.fetchall():
                        header_hash = self.maybe_from_hex(row[0])
                        ret[header_hash] = BlockRecord.from_bytes(row[1])

        return ret, peak[0]

    async def set_peak(self, header_hash: bytes32) -> None:
        # We need to be in a sqlite transaction here.
        # Note: we do not commit this to the database yet, as we need to also change the coin store

        if self.db_wrapper.db_version == 2:
            # Note: we use the key field as 0 just to ensure all inserts replace the existing row
            async with self.db_wrapper.writer_maybe_transaction() as conn:
                await conn.execute("INSERT OR REPLACE INTO current_peak VALUES(?, ?)", (0, header_hash))
        else:
            async with self.db_wrapper.writer_maybe_transaction() as conn:
                await conn.execute("UPDATE block_records SET is_peak=0 WHERE is_peak=1")
                await conn.execute(
                    "UPDATE block_records SET is_peak=1 WHERE header_hash=?",
                    (self.maybe_to_hex(header_hash),),
                )

    async def is_fully_compactified(self, header_hash: bytes32) -> Optional[bool]:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            async with conn.execute(
                "SELECT is_fully_compactified from full_blocks WHERE header_hash=?", (self.maybe_to_hex(header_hash),)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return bool(row[0])

    async def get_random_not_compactified(self, number: int) -> List[int]:

        if self.db_wrapper.db_version == 2:
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    f"SELECT height FROM full_blocks WHERE in_main_chain=1 AND is_fully_compactified=0 "
                    f"ORDER BY RANDOM() LIMIT {number}"
                ) as cursor:
                    rows = await cursor.fetchall()
        else:
            # Since orphan blocks do not get compactified, we need to check whether all blocks with a
            # certain height are not compact. And if we do have compact orphan blocks, then all that
            # happens is that the occasional chain block stays uncompact - not ideal, but harmless.
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    f"SELECT height FROM full_blocks GROUP BY height HAVING sum(is_fully_compactified)=0 "
                    f"ORDER BY RANDOM() LIMIT {number}"
                ) as cursor:
                    rows = await cursor.fetchall()

        heights = [int(row[0]) for row in rows]

        return heights

    async def count_compactified_blocks(self) -> int:
        if self.db_wrapper.db_version == 2:
            # DB V2 has an index on is_fully_compactified only for blocks in the main chain
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    "select count(*) from full_blocks where is_fully_compactified=1 and in_main_chain=1"
                ) as cursor:
                    row = await cursor.fetchone()
        else:
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute("select count(*) from full_blocks where is_fully_compactified=1") as cursor:
                    row = await cursor.fetchone()

        assert row is not None

        [count] = row
        return int(count)

    async def count_uncompactified_blocks(self) -> int:
        if self.db_wrapper.db_version == 2:
            # DB V2 has an index on is_fully_compactified only for blocks in the main chain
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute(
                    "select count(*) from full_blocks where is_fully_compactified=0 and in_main_chain=1"
                ) as cursor:
                    row = await cursor.fetchone()
        else:
            async with self.db_wrapper.reader_no_transaction() as conn:
                async with conn.execute("select count(*) from full_blocks where is_fully_compactified=0") as cursor:
                    row = await cursor.fetchone()

        assert row is not None

        [count] = row
        return int(count)
