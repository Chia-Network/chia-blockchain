import asyncio
import logging
from typing import Dict, List, Optional, Tuple

import aiosqlite

from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import SubEpochChallengeSegment, SubEpochSegments
from chia.util.ints import uint32
from chia.util.lru_cache import LRUCache

log = logging.getLogger(__name__)


class BlockStore:
    db: aiosqlite.Connection
    block_cache: LRUCache

    @classmethod
    async def create(cls, connection: aiosqlite.Connection):
        self = cls()

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db = connection
        await self.db.execute("pragma journal_mode=wal")
        await self.db.execute("pragma synchronous=2")
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS full_blocks(header_hash text PRIMARY KEY, height bigint,"
            "  is_block tinyint, is_fully_compactified tinyint, block blob)"
        )

        # Block records
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS block_records(header_hash "
            "text PRIMARY KEY, prev_hash text, height bigint,"
            "block blob, sub_epoch_summary blob, is_peak tinyint, is_block tinyint)"
        )

        # todo remove in v1.2
        await self.db.execute("DROP TABLE IF EXISTS sub_epoch_segments")

        # Sub epoch segments for weight proofs
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS sub_epoch_segments_v2(ses_height bigint PRIMARY KEY, challenge_segments blob)"
        )

        # Height index so we can look up in order of height for sync purposes
        await self.db.execute("CREATE INDEX IF NOT EXISTS full_block_height on full_blocks(height)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS is_block on full_blocks(is_block)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS is_fully_compactified on full_blocks(is_fully_compactified)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS height on block_records(height)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS hh on block_records(header_hash)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS peak on block_records(is_peak)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS is_block on block_records(is_block)")

        await self.db.commit()
        self.block_cache = LRUCache(1000)
        return self

    async def begin_transaction(self) -> None:
        # Also locks the coin store, since both stores must be updated at once
        cursor = await self.db.execute("BEGIN TRANSACTION")
        await cursor.close()

    async def commit_transaction(self) -> None:
        await self.db.commit()

    async def rollback_transaction(self) -> None:
        # Also rolls back the coin store, since both stores must be updated at once
        cursor = await self.db.execute("ROLLBACK")
        await cursor.close()

    async def add_full_block(self, block: FullBlock, block_record: BlockRecord) -> None:
        self.block_cache.put(block.header_hash, block)
        cursor_1 = await self.db.execute(
            "INSERT OR REPLACE INTO full_blocks VALUES(?, ?, ?, ?, ?)",
            (
                block.header_hash.hex(),
                block.height,
                int(block.is_transaction_block()),
                int(block.is_fully_compactified()),
                bytes(block),
            ),
        )

        await cursor_1.close()

        cursor_2 = await self.db.execute(
            "INSERT OR REPLACE INTO block_records VALUES(?, ?, ?, ?,?, ?, ?)",
            (
                block.header_hash.hex(),
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
        await cursor_2.close()
        await self.db.commit()

    async def persist_sub_epoch_challenge_segments(
        self, sub_epoch_summary_height: uint32, segments: List[SubEpochChallengeSegment]
    ) -> None:
        cursor_1 = await self.db.execute(
            "INSERT OR REPLACE INTO sub_epoch_segments_v2 VALUES(?, ?)",
            (sub_epoch_summary_height, bytes(SubEpochSegments(segments))),
        )
        await cursor_1.close()

    async def get_sub_epoch_challenge_segments(
        self,
        sub_epoch_summary_height: uint32,
    ) -> Optional[List[SubEpochChallengeSegment]]:
        cursor = await self.db.execute(
            "SELECT challenge_segments from sub_epoch_segments_v2 WHERE ses_height=?", (sub_epoch_summary_height,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return SubEpochSegments.from_bytes(row[0]).challenge_segments
        return None

    async def delete_sub_epoch_challenge_segments(self, fork_height: uint32) -> None:
        cursor = await self.db.execute("delete from sub_epoch_segments_v2 WHERE ses_height>?", (fork_height,))
        await cursor.close()

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        cached = self.block_cache.get(header_hash)
        if cached is not None:
            return cached
        cursor = await self.db.execute("SELECT block from full_blocks WHERE header_hash=?", (header_hash.hex(),))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return FullBlock.from_bytes(row[0])
        return None

    async def get_full_blocks_at(self, heights: List[uint32]) -> List[FullBlock]:
        if len(heights) == 0:
            return []

        heights_db = tuple(heights)
        formatted_str = f'SELECT block from full_blocks WHERE height in ({"?," * (len(heights_db) - 1)}?)'
        cursor = await self.db.execute(formatted_str, heights_db)
        rows = await cursor.fetchall()
        await cursor.close()
        return [FullBlock.from_bytes(row[0]) for row in rows]

    async def get_block_records_at(self, heights: List[uint32]) -> List[BlockRecord]:
        if len(heights) == 0:
            return []
        heights_db = tuple(heights)
        formatted_str = (
            f'SELECT block from block_records WHERE height in ({"?," * (len(heights_db) - 1)}?) ORDER BY height ASC;'
        )
        cursor = await self.db.execute(formatted_str, heights_db)
        rows = await cursor.fetchall()
        await cursor.close()
        return [BlockRecord.from_bytes(row[0]) for row in rows]

    async def get_blocks_by_hash(self, header_hashes: List[bytes32]) -> List[FullBlock]:
        """
        Returns a list of Full Blocks blocks, ordered by the same order in which header_hashes are passed in.
        Throws an exception if the blocks are not present
        """

        if len(header_hashes) == 0:
            return []

        header_hashes_db = tuple([hh.hex() for hh in header_hashes])
        formatted_str = f'SELECT block from full_blocks WHERE header_hash in ({"?," * (len(header_hashes_db) - 1)}?)'
        cursor = await self.db.execute(formatted_str, header_hashes_db)
        rows = await cursor.fetchall()
        await cursor.close()
        all_blocks: Dict[bytes32, FullBlock] = {}
        for row in rows:
            full_block: FullBlock = FullBlock.from_bytes(row[0])
            all_blocks[full_block.header_hash] = full_block
        ret: List[FullBlock] = []
        for hh in header_hashes:
            if hh not in all_blocks:
                raise ValueError(f"Header hash {hh} not in the blockchain")
            ret.append(all_blocks[hh])
        return ret

    async def get_header_blocks_in_range(
        self,
        start: int,
        stop: int,
    ) -> Dict[bytes32, HeaderBlock]:

        formatted_str = f"SELECT header_hash,block from full_blocks WHERE height >= {start} and height <= {stop}"

        cursor = await self.db.execute(formatted_str)
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, HeaderBlock] = {}
        for row in rows:
            # Ugly hack, until full_block.get_block_header is rewritten as part of generator runner change
            await asyncio.sleep(0.001)
            header_hash = bytes.fromhex(row[0])
            full_block: FullBlock = FullBlock.from_bytes(row[1])
            ret[header_hash] = full_block.get_block_header()

        return ret

    async def get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        cursor = await self.db.execute(
            "SELECT block from block_records WHERE header_hash=?",
            (header_hash.hex(),),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return BlockRecord.from_bytes(row[0])
        return None

    async def get_block_records(
        self,
    ) -> Tuple[Dict[bytes32, BlockRecord], Optional[bytes32]]:
        """
        Returns a dictionary with all blocks, as well as the header hash of the peak,
        if present.
        """
        cursor = await self.db.execute("SELECT * from block_records")
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, BlockRecord] = {}
        peak: Optional[bytes32] = None
        for row in rows:
            header_hash = bytes.fromhex(row[0])
            ret[header_hash] = BlockRecord.from_bytes(row[3])
            if row[5]:
                assert peak is None  # Sanity check, only one peak
                peak = header_hash
        return ret, peak

    async def get_block_records_in_range(
        self,
        start: int,
        stop: int,
    ) -> Dict[bytes32, BlockRecord]:
        """
        Returns a dictionary with all blocks in range between start and stop
        if present.
        """

        formatted_str = f"SELECT header_hash, block from block_records WHERE height >= {start} and height <= {stop}"

        cursor = await self.db.execute(formatted_str)
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, BlockRecord] = {}
        for row in rows:
            header_hash = bytes.fromhex(row[0])
            ret[header_hash] = BlockRecord.from_bytes(row[1])

        return ret

    async def get_block_records_close_to_peak(
        self, blocks_n: int
    ) -> Tuple[Dict[bytes32, BlockRecord], Optional[bytes32]]:
        """
        Returns a dictionary with all blocks that have height >= peak height - blocks_n, as well as the
        peak header hash.
        """

        res = await self.db.execute("SELECT * from block_records WHERE is_peak = 1")
        peak_row = await res.fetchone()
        await res.close()
        if peak_row is None:
            return {}, None

        formatted_str = f"SELECT header_hash, block  from block_records WHERE height >= {peak_row[2] - blocks_n}"
        cursor = await self.db.execute(formatted_str)
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, BlockRecord] = {}
        for row in rows:
            header_hash = bytes.fromhex(row[0])
            ret[header_hash] = BlockRecord.from_bytes(row[1])
        return ret, bytes.fromhex(peak_row[0])

    async def get_peak_height_dicts(self) -> Tuple[Dict[uint32, bytes32], Dict[uint32, SubEpochSummary]]:
        """
        Returns a dictionary with all blocks, as well as the header hash of the peak,
        if present.
        """

        res = await self.db.execute("SELECT * from block_records WHERE is_peak = 1")
        row = await res.fetchone()
        await res.close()
        if row is None:
            return {}, {}

        peak: bytes32 = bytes.fromhex(row[0])
        cursor = await self.db.execute("SELECT header_hash,prev_hash,height,sub_epoch_summary from block_records")
        rows = await cursor.fetchall()
        await cursor.close()
        hash_to_prev_hash: Dict[bytes32, bytes32] = {}
        hash_to_height: Dict[bytes32, uint32] = {}
        hash_to_summary: Dict[bytes32, SubEpochSummary] = {}

        for row in rows:
            hash_to_prev_hash[bytes.fromhex(row[0])] = bytes.fromhex(row[1])
            hash_to_height[bytes.fromhex(row[0])] = row[2]
            if row[3] is not None:
                hash_to_summary[bytes.fromhex(row[0])] = SubEpochSummary.from_bytes(row[3])

        height_to_hash: Dict[uint32, bytes32] = {}
        sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}

        curr_header_hash = peak
        curr_height = hash_to_height[curr_header_hash]
        while True:
            height_to_hash[curr_height] = curr_header_hash
            if curr_header_hash in hash_to_summary:
                sub_epoch_summaries[curr_height] = hash_to_summary[curr_header_hash]
            if curr_height == 0:
                break
            curr_header_hash = hash_to_prev_hash[curr_header_hash]
            curr_height = hash_to_height[curr_header_hash]
        return height_to_hash, sub_epoch_summaries

    async def set_peak(self, header_hash: bytes32) -> None:
        # We need to be in a sqlite transaction here.
        # Note: we do not commit this to the database yet, as we need to also change the coin store
        cursor_1 = await self.db.execute("UPDATE block_records SET is_peak=0 WHERE is_peak=1")
        await cursor_1.close()
        cursor_2 = await self.db.execute(
            "UPDATE block_records SET is_peak=1 WHERE header_hash=?",
            (header_hash.hex(),),
        )
        await cursor_2.close()

    async def is_fully_compactified(self, header_hash: bytes32) -> Optional[bool]:
        cursor = await self.db.execute(
            "SELECT is_fully_compactified from full_blocks WHERE header_hash=?", (header_hash.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return bool(row[0])

    async def get_first_not_compactified(self, min_height: int) -> Optional[int]:
        cursor = await self.db.execute(
            "SELECT MIN(height) from full_blocks WHERE is_fully_compactified=0 AND height>=?", (min_height,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return int(row[0])
