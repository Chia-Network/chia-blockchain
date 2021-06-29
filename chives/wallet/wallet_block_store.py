from typing import Dict, List, Optional, Tuple

import aiosqlite

from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.header_block import HeaderBlock
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint32, uint64
from chia.util.lru_cache import LRUCache
from chia.wallet.block_record import HeaderBlockRecord


class WalletBlockStore:
    """
    This object handles HeaderBlocks and Blocks stored in DB used by wallet.
    """

    db: aiosqlite.Connection
    db_wrapper: DBWrapper
    block_cache: LRUCache

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()

        self.db_wrapper = db_wrapper
        self.db = db_wrapper.db
        await self.db.execute("pragma journal_mode=wal")
        await self.db.execute("pragma synchronous=2")

        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS header_blocks(header_hash text PRIMARY KEY, height int,"
            " timestamp int, block blob)"
        )

        await self.db.execute("CREATE INDEX IF NOT EXISTS header_hash on header_blocks(header_hash)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS timestamp on header_blocks(timestamp)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS height on header_blocks(height)")

        # Block records
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS block_records(header_hash "
            "text PRIMARY KEY, prev_hash text, height bigint, weight bigint, total_iters text,"
            "block blob, sub_epoch_summary blob, is_peak tinyint)"
        )

        # Height index so we can look up in order of height for sync purposes
        await self.db.execute("CREATE INDEX IF NOT EXISTS height on block_records(height)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS hh on block_records(header_hash)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS peak on block_records(is_peak)")
        await self.db.commit()
        self.block_cache = LRUCache(1000)
        return self

    async def _clear_database(self):
        cursor_2 = await self.db.execute("DELETE FROM header_blocks")
        await cursor_2.close()
        await self.db.commit()

    async def add_block_record(self, header_block_record: HeaderBlockRecord, block_record: BlockRecord):
        """
        Adds a block record to the database. This block record is assumed to be connected
        to the chain, but it may or may not be in the LCA path.
        """
        cached = self.block_cache.get(header_block_record.header_hash)
        if cached is not None:
            # Since write to db can fail, we remove from cache here to avoid potential inconsistency
            # Adding to cache only from reading
            self.block_cache.put(header_block_record.header_hash, None)

        if header_block_record.header.foliage_transaction_block is not None:
            timestamp = header_block_record.header.foliage_transaction_block.timestamp
        else:
            timestamp = uint64(0)
        cursor = await self.db.execute(
            "INSERT OR REPLACE INTO header_blocks VALUES(?, ?, ?, ?)",
            (
                header_block_record.header_hash.hex(),
                header_block_record.height,
                timestamp,
                bytes(header_block_record),
            ),
        )

        await cursor.close()
        cursor_2 = await self.db.execute(
            "INSERT OR REPLACE INTO block_records VALUES(?, ?, ?, ?, ?, ?, ?,?)",
            (
                header_block_record.header.header_hash.hex(),
                header_block_record.header.prev_header_hash.hex(),
                header_block_record.header.height,
                header_block_record.header.weight.to_bytes(128 // 8, "big", signed=False).hex(),
                header_block_record.header.total_iters.to_bytes(128 // 8, "big", signed=False).hex(),
                bytes(block_record),
                None
                if block_record.sub_epoch_summary_included is None
                else bytes(block_record.sub_epoch_summary_included),
                False,
            ),
        )

        await cursor_2.close()

    async def get_header_block_at(self, heights: List[uint32]) -> List[HeaderBlock]:
        if len(heights) == 0:
            return []

        heights_db = tuple(heights)
        formatted_str = f'SELECT block from header_blocks WHERE height in ({"?," * (len(heights_db) - 1)}?)'
        cursor = await self.db.execute(formatted_str, heights_db)
        rows = await cursor.fetchall()
        await cursor.close()
        return [HeaderBlock.from_bytes(row[0]) for row in rows]

    async def get_header_block_record(self, header_hash: bytes32) -> Optional[HeaderBlockRecord]:
        """Gets a block record from the database, if present"""
        cached = self.block_cache.get(header_hash)
        if cached is not None:
            return cached
        cursor = await self.db.execute("SELECT block from header_blocks WHERE header_hash=?", (header_hash.hex(),))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            hbr: HeaderBlockRecord = HeaderBlockRecord.from_bytes(row[0])
            self.block_cache.put(hbr.header_hash, hbr)
            return hbr
        else:
            return None

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
        cursor = await self.db.execute("SELECT header_hash, block, is_peak from block_records")
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, BlockRecord] = {}
        peak: Optional[bytes32] = None
        for row in rows:
            header_hash_bytes, block_record_bytes, is_peak = row
            header_hash = bytes.fromhex(header_hash_bytes)
            ret[header_hash] = BlockRecord.from_bytes(block_record_bytes)
            if is_peak:
                assert peak is None  # Sanity check, only one peak
                peak = header_hash
        return ret, peak

    async def set_peak(self, header_hash: bytes32) -> None:
        cursor_1 = await self.db.execute("UPDATE block_records SET is_peak=0 WHERE is_peak=1")
        await cursor_1.close()
        cursor_2 = await self.db.execute(
            "UPDATE block_records SET is_peak=1 WHERE header_hash=?",
            (header_hash.hex(),),
        )
        await cursor_2.close()

    async def get_block_records_close_to_peak(
        self, blocks_n: int
    ) -> Tuple[Dict[bytes32, BlockRecord], Optional[bytes32]]:
        """
        Returns a dictionary with all blocks, as well as the header hash of the peak,
        if present.
        """

        res = await self.db.execute("SELECT header_hash, height from block_records WHERE is_peak = 1")
        row = await res.fetchone()
        await res.close()
        if row is None:
            return {}, None
        header_hash_bytes, peak_height = row
        peak: bytes32 = bytes32(bytes.fromhex(header_hash_bytes))

        formatted_str = f"SELECT header_hash, block from block_records WHERE height >= {peak_height - blocks_n}"
        cursor = await self.db.execute(formatted_str)
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, BlockRecord] = {}
        for row in rows:
            header_hash_bytes, block_record_bytes = row
            header_hash = bytes.fromhex(header_hash_bytes)
            ret[header_hash] = BlockRecord.from_bytes(block_record_bytes)
        return ret, peak

    async def get_header_blocks_in_range(
        self,
        start: int,
        stop: int,
    ) -> Dict[bytes32, HeaderBlock]:

        formatted_str = f"SELECT header_hash, block from header_blocks WHERE height >= {start} and height <= {stop}"

        cursor = await self.db.execute(formatted_str)
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, HeaderBlock] = {}
        for row in rows:
            header_hash_bytes, block_record_bytes = row
            header_hash = bytes.fromhex(header_hash_bytes)
            ret[header_hash] = HeaderBlock.from_bytes(block_record_bytes)

        return ret

    async def get_block_records_in_range(
        self,
        start: int,
        stop: int,
    ) -> Dict[bytes32, BlockRecord]:
        """
        Returns a dictionary with all blocks, as well as the header hash of the peak,
        if present.
        """

        formatted_str = f"SELECT header_hash, block from block_records WHERE height >= {start} and height <= {stop}"

        cursor = await self.db.execute(formatted_str)
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, BlockRecord] = {}
        for row in rows:
            header_hash_bytes, block_record_bytes = row
            header_hash = bytes.fromhex(header_hash_bytes)
            ret[header_hash] = BlockRecord.from_bytes(block_record_bytes)

        return ret

    async def get_peak_heights_dicts(self) -> Tuple[Dict[uint32, bytes32], Dict[uint32, SubEpochSummary]]:
        """
        Returns a dictionary with all blocks, as well as the header hash of the peak,
        if present.
        """

        res = await self.db.execute("SELECT header_hash from block_records WHERE is_peak = 1")
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
