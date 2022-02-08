import logging
from databases import Database
from sqlalchemy import bindparam
from sqlalchemy.sql import text
from typing import Dict, List, Optional, Tuple, Any

import zstd

from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.weight_proof import SubEpochChallengeSegment, SubEpochSegments
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32
from chia.util.lru_cache import LRUCache
from chia.util import dialect_utils

log = logging.getLogger(__name__)


class BlockStore:
    db: Database
    block_cache: LRUCache
    db_wrapper: DBWrapper
    ses_challenge_cache: LRUCache

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db_wrapper = db_wrapper
        self.db = db_wrapper.db

        async with self.db.connection() as connection:
            async with connection.transaction():
                if self.db_wrapper.db_version == 2:

                    # TODO: most data in block is duplicated in block_record. The only
                    # reason for this is that our parsing of a FullBlock is so slow,
                    # it's faster to store duplicate data to parse less when we just
                    # need the BlockRecord. Once we fix the parsing (and data structure)
                    # of FullBlock, this can use less space
                    await self.db.execute(
                        "CREATE TABLE IF NOT EXISTS full_blocks("
                        f"header_hash {dialect_utils.data_type('blob', self.db.url.dialect)} PRIMARY KEY,"
                        f"prev_hash {dialect_utils.data_type('blob', self.db.url.dialect)},"
                        "height bigint,"
                        f"sub_epoch_summary {dialect_utils.data_type('blob', self.db.url.dialect)},"
                        f"is_fully_compactified {dialect_utils.data_type('tinyint', self.db.url.dialect)},"
                        f"in_main_chain {dialect_utils.data_type('tinyint', self.db.url.dialect)},"
                        f"block {dialect_utils.data_type('blob', self.db.url.dialect)},"
                        f"block_record {dialect_utils.data_type('blob', self.db.url.dialect)})"
                    )

                    # This is a single-row table containing the hash of the current
                    # peak. The "key" field is there to make update statements simple
                    await self.db.execute(f"CREATE TABLE IF NOT EXISTS current_peak(key int PRIMARY KEY, hash {dialect_utils.data_type('blob', self.db.url.dialect)})")

                    await dialect_utils.create_index_if_not_exists(self.db, 'height', 'full_blocks', ['height'])

                    # Sub epoch segments for weight proofs
                    await self.db.execute(
                        "CREATE TABLE IF NOT EXISTS sub_epoch_segments_v3("
                        f"ses_block_hash {dialect_utils.data_type('blob', self.db.url.dialect)} PRIMARY KEY,"
                        f"challenge_segments {dialect_utils.data_type('blob', self.db.url.dialect)})"
                    )

                    await dialect_utils.create_index_if_not_exists(self.db, 'is_fully_compactified', 'full_blocks', ['is_fully_compactified', 'in_main_chain'], 'in_main_chain=1')
                    await dialect_utils.create_index_if_not_exists(self.db, 'main_chain', 'full_blocks', ['height', 'in_main_chain'], 'in_main_chain=1')
                else:

                    await self.db.execute(
                        f"CREATE TABLE IF NOT EXISTS full_blocks(header_hash {dialect_utils.data_type('text-as-index', self.db.url.dialect)} PRIMARY KEY, height bigint,"
                        f" is_block {dialect_utils.data_type('tinyint', self.db.url.dialect)}, is_fully_compactified {dialect_utils.data_type('tinyint', self.db.url.dialect)}, block {dialect_utils.data_type('blob', self.db.url.dialect)})"
                    )

                    # Block records
                    await self.db.execute(
                        "CREATE TABLE IF NOT EXISTS block_records(header_hash "
                        f"{dialect_utils.data_type('text-as-index', self.db.url.dialect)} PRIMARY KEY, prev_hash text, height bigint,"
                        f"block {dialect_utils.data_type('blob', self.db.url.dialect)}, sub_epoch_summary {dialect_utils.data_type('blob', self.db.url.dialect)}, is_peak {dialect_utils.data_type('tinyint', self.db.url.dialect)}, is_block {dialect_utils.data_type('tinyint', self.db.url.dialect)})"
                    )

                    # Sub epoch segments for weight proofs
                    await self.db.execute(
                        f"CREATE TABLE IF NOT EXISTS sub_epoch_segments_v3(ses_block_hash {dialect_utils.data_type('text-as-index', self.db.url.dialect)} PRIMARY KEY,"
                        f"challenge_segments {dialect_utils.data_type('blob', self.db.url.dialect)})"
                    )

                    # Height index so we can look up in order of height for sync purposes
                    await dialect_utils.create_index_if_not_exists(self.db, 'full_block_height', 'full_blocks', ['height'])
                    await dialect_utils.create_index_if_not_exists(self.db, 'is_fully_compactified', 'full_blocks', ['is_fully_compactified'])

                    await dialect_utils.create_index_if_not_exists(self.db, 'height', 'block_records', ['height'])

                    await dialect_utils.create_index_if_not_exists(self.db, 'peak', 'block_records', ['is_peak'], 'is_peak = 1')


        self.block_cache = LRUCache(1000)
        self.ses_challenge_cache = LRUCache(50)
        return self

    def maybe_from_hex(self, field: Any) -> bytes:
        if self.db_wrapper.db_version == 2:
            return field
        else:
            return bytes.fromhex(field)

    def maybe_to_hex(self, field: bytes) -> Any:
        if self.db_wrapper.db_version == 2:
            return field
        else:
            return field.hex()

    def compress(self, block: FullBlock) -> bytes:
        return zstd.compress(bytes(block))

    def maybe_decompress(self, block_bytes: bytes) -> FullBlock:
        if self.db_wrapper.db_version == 2:
            return FullBlock.from_bytes(zstd.decompress(block_bytes))
        else:
            return FullBlock.from_bytes(block_bytes)

    async def rollback(self, height: int) -> None:
        if self.db_wrapper.db_version == 2:
            await self.db.execute(
                "UPDATE full_blocks SET in_main_chain=0 WHERE height>:height AND in_main_chain=1", {"height": height}
            )

    async def set_in_chain(self, header_hashes: List[bytes32]) -> None:
        if self.db_wrapper.db_version == 2:
            await self.db.execute_many(
                "UPDATE full_blocks SET in_main_chain=1 WHERE header_hash=:header_hash", list(map(lambda header_hash: {"header_hash": header_hash}, header_hashes))
            )

    async def replace_proof(self, header_hash: bytes32, block: FullBlock) -> None:

        assert header_hash == block.header_hash

        block_bytes: bytes
        if self.db_wrapper.db_version == 2:
            block_bytes = self.compress(block)
        else:
            block_bytes = bytes(block)

        self.block_cache.put(header_hash, block)

        await self.db.execute(
            "UPDATE full_blocks SET block=:block,is_fully_compactified=:is_fully_compactified WHERE header_hash=:header_hash",
            {
                "block": block_bytes,
                "is_fully_compactified": int(block.is_fully_compactified()),
                "header_hash": self.maybe_to_hex(header_hash),
            },
        )

    async def add_full_block(self, header_hash: bytes32, block: FullBlock, block_record: BlockRecord) -> None:
        self.block_cache.put(header_hash, block)

        if self.db_wrapper.db_version == 2:

            ses: Optional[bytes] = (
                None
                if block_record.sub_epoch_summary_included is None
                else bytes(block_record.sub_epoch_summary_included)
            )
            row_to_insert = {
                "header_hash": header_hash,
                "prev_hash": block.prev_header_hash,
                "height": int(block.height),
                "sub_epoch_summary": ses,
                "is_fully_compactified": int(block.is_fully_compactified()),
                "in_main_chain": False,  # in_main_chain
                "block": self.compress(block),
                "block_record": bytes(block_record),
            }

            await self.db.execute(
                dialect_utils.insert_or_ignore_query("full_blocks", ["header_hash"], row_to_insert.keys(), self.db.url.dialect),
                row_to_insert
            )

        else:
            row_to_insert = {
                "header_hash": header_hash.hex(),
                "height": int(block.height),
                "is_block": int(block.is_transaction_block()),
                "is_fully_compactified": int(block.is_fully_compactified()),
                "block": bytes(block),
            }

            await self.db.execute(
                dialect_utils.insert_or_ignore_query("full_blocks", ["header_hash"], row_to_insert.keys(), self.db.url.dialect),
                row_to_insert
            )

            row_to_insert = {
                "header_hash": header_hash.hex(),
                "prev_hash": block.prev_header_hash.hex(),
                "height": int(block.height),
                "block": bytes(block_record),
                "sub_epoch_summary":
                    None
                    if block_record.sub_epoch_summary_included is None
                    else bytes(block_record.sub_epoch_summary_included),
                "is_peak": False,
                "is_block": block.is_transaction_block(),
            }
            await self.db.execute(
                dialect_utils.insert_or_ignore_query("block_records", ["header_hash"], row_to_insert.keys(), self.db.url.dialect),
                row_to_insert
            )

    async def persist_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32, segments: List[SubEpochChallengeSegment]
    ) -> None:
        async with self.db_wrapper.lock:
            row_to_insert = {"ses_block_hash": self.maybe_to_hex(ses_block_hash), "challenge_segments": bytes(SubEpochSegments(segments))}
            await self.db.execute(
                dialect_utils.upsert_query("sub_epoch_segments_v3", ["ses_block_hash"], row_to_insert.keys(), self.db.url.dialect),
                row_to_insert,
            )

    async def get_sub_epoch_challenge_segments(
        self,
        ses_block_hash: bytes32,
    ) -> Optional[List[SubEpochChallengeSegment]]:
        cached = self.ses_challenge_cache.get(ses_block_hash)
        if cached is not None:
            return cached

        row = await self.db.fetch_one(
            "SELECT challenge_segments from sub_epoch_segments_v3 WHERE ses_block_hash=:ses_block_hash",
            {"ses_block_hash": self.maybe_to_hex(ses_block_hash)},
        )

        if row is not None:
            challenge_segments = SubEpochSegments.from_bytes(row[0]).challenge_segments
            self.ses_challenge_cache.put(ses_block_hash, challenge_segments)
            return challenge_segments
        return None

    def rollback_cache_block(self, header_hash: bytes32):
        try:
            self.block_cache.remove(header_hash)
        except KeyError:
            # this is best effort. When rolling back, we may not have added the
            # block to the cache yet
            pass

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        cached = self.block_cache.get(header_hash)
        if cached is not None:
            log.debug(f"cache hit for block {header_hash.hex()}")
            return cached
        log.debug(f"cache miss for block {header_hash.hex()}")
        row = await self.db.fetch_one(
            "SELECT block from full_blocks WHERE header_hash=:header_hash", {"header_hash": self.maybe_to_hex(header_hash)}
        )
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
        row = await self.db.fetch_one(
            "SELECT block from full_blocks WHERE header_hash=:header_hash", {"header_hash": self.maybe_to_hex(header_hash)}
        )
        if row is not None:
            if self.db_wrapper.db_version == 2:
                return zstd.decompress(row[0])
            else:
                return row[0]

        return None

    async def get_full_blocks_at(self, heights: List[uint32]) -> List[FullBlock]:
        if len(heights) == 0:
            return []

        heights_db = list(map(lambda height: int(height), heights))
        query = text('SELECT block from full_blocks WHERE height in :heights')
        query = query.bindparams(bindparam("heights", heights_db, expanding=True))
        rows = await self.db.fetch_all(query)

        ret: List[FullBlock] = []
        for row in rows:
            ret.append(self.maybe_decompress(row[0]))
        return ret

    async def get_block_records_by_hash(self, header_hashes: List[bytes32]):
        """
        Returns a list of Block Records, ordered by the same order in which header_hashes are passed in.
        Throws an exception if the blocks are not present
        """
        if len(header_hashes) == 0:
            return []

        all_blocks: Dict[bytes32, BlockRecord] = {}
        if self.db_wrapper.db_version == 2:
            query = text("SELECT header_hash, block_record FROM full_blocks WHERE header_hash in :header_hashes")
            query = query.bindparams(bindparam("header_hashes", header_hashes, expanding=True))
            rows = await self.db.fetch_all(query)
            for row in rows:
                header_hash = bytes32(row[0])
                all_blocks[header_hash] = BlockRecord.from_bytes(row[1])
        else:
            query = text('SELECT block from block_records WHERE header_hash in :header_hashes')
            query = query.bindparams(bindparam('header_hashes', tuple([hh.hex() for hh in header_hashes]), expanding = True))
            rows = await self.db.fetch_all(query)
            for row in rows:
                block_rec: BlockRecord = BlockRecord.from_bytes(row[0])
                all_blocks[block_rec.header_hash] = block_rec

        ret: List[BlockRecord] = []
        for hh in header_hashes:
            if hh not in all_blocks:
                raise ValueError(f"Header hash {hh} not in the blockchain")
            ret.append(all_blocks[hh])
        return ret

    async def get_blocks_by_hash(self, header_hashes: List[bytes32]) -> List[FullBlock]:
        """
        Returns a list of Full Blocks blocks, ordered by the same order in which header_hashes are passed in.
        Throws an exception if the blocks are not present
        """

        if len(header_hashes) == 0:
            return []

        header_hashes_db: Tuple[Any, ...]
        if self.db_wrapper.db_version == 2:
            header_hashes_db = tuple(header_hashes)
        else:
            header_hashes_db = tuple([hh.hex() for hh in header_hashes])
        query = text('SELECT header_hash, block from full_blocks WHERE header_hash in :header_hashes')
        query = query.bindparams(bindparam('header_hashes', header_hashes_db, expanding = True))
        all_blocks: Dict[bytes32, FullBlock] = {}
        rows = await self.db.fetch_all(query)
        for row in rows:
            header_hash = self.maybe_from_hex(row[0])
            full_block: FullBlock = self.maybe_decompress(row[1])
            # TODO: address hint error and remove ignore
            #       error: Invalid index type "bytes" for "Dict[bytes32, FullBlock]";
            # expected type "bytes32"  [index]
            all_blocks[header_hash] = full_block  # type: ignore[index]
            self.block_cache.put(header_hash, full_block)
        ret: List[FullBlock] = []
        for hh in header_hashes:
            if hh not in all_blocks:
                raise ValueError(f"Header hash {hh} not in the blockchain")
            ret.append(all_blocks[hh])
        return ret

    async def get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:

        if self.db_wrapper.db_version == 2:

            row = await self.db.fetch_one("SELECT block_record FROM full_blocks WHERE header_hash=:header_hash", {"header_hash": header_hash})
            if row is not None:
                return BlockRecord.from_bytes(row[0])

        else:
            row = await self.db.fetch_one(
                "SELECT block from block_records WHERE header_hash=:header_hash",
                {"header_hash": header_hash.hex()},
            )
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

            rows = await self.db.fetch_all(
                "SELECT header_hash, block_record FROM full_blocks WHERE height >= :start AND height <= :stop",
                {"start": int(start), "stop": int(stop)},
            )
            for row in rows:
                header_hash = bytes32(row[0])
                ret[header_hash] = BlockRecord.from_bytes(row[1])

        else:

            formatted_str = f"SELECT header_hash, block from block_records WHERE height >= {start} and height <= {stop}"

            rows = await self.db.fetch_all(formatted_str)
            for row in rows:
                header_hash = bytes32(self.maybe_from_hex(row[0]))
                ret[header_hash] = BlockRecord.from_bytes(row[1])

        return ret

    async def get_peak(self) -> Optional[Tuple[bytes32, uint32]]:

        if self.db_wrapper.db_version == 2:
            peak_row = await self.db.fetch_one("SELECT hash FROM current_peak WHERE key = 0")
            if peak_row is None:
                return None

            peak_height = await self.db.fetch_one("SELECT height FROM full_blocks WHERE header_hash=:header_hash", {"header_hash": peak_row[0]})
            if peak_height is None:
                return None
            return bytes32(peak_row[0]), uint32(peak_height[0])
        else:
            peak_row = await self.db.fetch_one("SELECT header_hash, height from block_records WHERE is_peak = 1")
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

            rows = await self.db.fetch_all(
                "SELECT header_hash, block_record FROM full_blocks WHERE height >= min_height",
                {"min_height": int(peak[1] - blocks_n)},
            )
            for row in rows:
                header_hash = bytes32(row[0])
                ret[header_hash] = BlockRecord.from_bytes(row[1])

        else:
            formatted_str = f"SELECT header_hash, block  from block_records WHERE height >= {int(peak[1] - blocks_n)}"
            rows = await self.db.fetch_all(formatted_str)
            for row in rows:
                header_hash = bytes32(self.maybe_from_hex(row[0]))
                ret[header_hash] = BlockRecord.from_bytes(row[1])

        return ret, peak[0]

    async def set_peak(self, header_hash: bytes32) -> None:
        # We need to be in a sqlite transaction here.
        # Note: we do not commit this to the database yet, as we need to also change the coin store

        if self.db_wrapper.db_version == 2:
            # Note: we use the key field as 0 just to ensure all inserts replace the existing row
            row_to_insert = {"key": 0, "header_hash": header_hash}
            await self.db.execute(dialect_utils.upsert_query('current_peak', ['key'], row_to_insert.keys(), self.db.url.dialect), row_to_insert)
        else:
            await self.db.execute("UPDATE block_records SET is_peak=0 WHERE is_peak=1")
            await self.db.execute(
                "UPDATE block_records SET is_peak=1 WHERE header_hash=:header_hash",
                {"header_hash": self.maybe_to_hex(header_hash)},
            )

    async def is_fully_compactified(self, header_hash: bytes32) -> Optional[bool]:
        row = await self.db.fetch_one(
            "SELECT is_fully_compactified from full_blocks WHERE header_hash=:header_hash", {"header_hash": self.maybe_to_hex(header_hash)}
        )
        if row is None:
            return None
        return bool(row[0])

    async def get_random_not_compactified(self, number: int) -> List[int]:

        if self.db_wrapper.db_version == 2:
            rows = await self.db.fetch_all(
                f"SELECT height FROM full_blocks WHERE in_main_chain=1 AND is_fully_compactified=0 "
                f"ORDER BY RANDOM() LIMIT {number}"
            )
        else:
            # Since orphan blocks do not get compactified, we need to check whether all blocks with a
            # certain height are not compact. And if we do have compact orphan blocks, then all that
            # happens is that the occasional chain block stays uncompact - not ideal, but harmless.
            rows = await self.db.fetch_all(
                f"SELECT height FROM full_blocks GROUP BY height HAVING sum(is_fully_compactified)=0 "
                f"ORDER BY RANDOM() LIMIT {number}"
            )

        heights = [int(row[0]) for row in rows]

        return heights

    async def count_compactified_blocks(self) -> int:
        row = await self.db.fetch_one("select count(*) from full_blocks where is_fully_compactified=1")

        assert row is not None

        [count] = row
        return int(count)

    async def count_uncompactified_blocks(self) -> int:
        row = await self.db.fetch_one("select count(*) from full_blocks where is_fully_compactified=0")

        assert row is not None

        [count] = row
        return int(count)
