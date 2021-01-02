from typing import Dict, Optional, Tuple, List
import aiosqlite

from src.consensus.sub_block_record import SubBlockRecord
from src.types.header_block import HeaderBlock
from src.util.ints import uint32, uint64
from src.wallet.block_record import HeaderBlockRecord
from src.types.sized_bytes import bytes32


class WalletBlockStore:
    """
    This object handles HeaderBlocks and SubBlocks stored in DB used by wallet.
    """

    db: aiosqlite.Connection

    @classmethod
    async def create(cls, connection: aiosqlite.Connection):
        self = cls()

        self.db = connection

        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS header_blocks(header_hash text PRIMARY KEY, sub_height int, height int,"
            " timestamp int, block blob)"
        )

        await self.db.execute("CREATE INDEX IF NOT EXISTS header_hash on header_blocks(header_hash)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS timestamp on header_blocks(timestamp)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS sub_height on header_blocks(sub_height)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS height on header_blocks(height)")

        # Sub block records
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS sub_block_records(header_hash "
            "text PRIMARY KEY, prev_hash text, sub_height bigint, height int, weight bigint, total_iters text,"
            "sub_block blob, is_peak tinyint)"
        )

        # Height index so we can look up in order of height for sync purposes
        await self.db.execute("CREATE INDEX IF NOT EXISTS sub_block_height on sub_block_records(sub_height)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS height on sub_block_records(height)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS hh on sub_block_records(header_hash)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS peak on sub_block_records(is_peak)")
        await self.db.commit()

        await self.db.commit()
        return self

    async def _clear_database(self):
        cursor_2 = await self.db.execute("DELETE FROM header_blocks")
        await cursor_2.close()
        await self.db.commit()

    async def rollback_lca_to_block(self, block_index):
        # TODO
        pass

    async def add_block_record(self, block_record: HeaderBlockRecord, sub_block: SubBlockRecord):
        """
        Adds a block record to the database. This block record is assumed to be connected
        to the chain, but it may or may not be in the LCA path.
        """
        if block_record.header.foliage_block is not None:
            timestamp = block_record.header.foliage_block.timestamp
        else:
            timestamp = uint64(0)
        cursor = await self.db.execute(
            "INSERT OR REPLACE INTO header_blocks VALUES(?, ?, ?, ?, ?)",
            (
                block_record.header_hash.hex(),
                block_record.sub_block_height,
                sub_block.height,
                timestamp,
                bytes(block_record),
            ),
        )

        await cursor.close()
        cursor_2 = await self.db.execute(
            "INSERT OR REPLACE INTO sub_block_records VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                block_record.header.header_hash.hex(),
                block_record.header.prev_header_hash.hex(),
                block_record.header.sub_block_height,
                block_record.header.height,
                block_record.header.weight.to_bytes(128 // 8, "big", signed=False).hex(),
                block_record.header.total_iters.to_bytes(128 // 8, "big", signed=False).hex(),
                bytes(sub_block),
                False,
            ),
        )
        await cursor_2.close()
        await self.db.commit()

    async def get_header_block(self, header_hash: bytes32) -> Optional[HeaderBlock]:
        """Gets a block record from the database, if present"""
        cursor = await self.db.execute("SELECT * from header_blocks WHERE header_hash=?", (header_hash.hex(),))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            hbr = HeaderBlockRecord.from_bytes(row[4])
            return hbr.header
        else:
            return None

    async def get_header_block_at(self, sub_heights: List[uint32]) -> List[HeaderBlock]:
        if len(sub_heights) == 0:
            return []

        heights_db = tuple(sub_heights)
        formatted_str = f'SELECT block from header_blocks WHERE sub_height in ({"?," * (len(heights_db) - 1)}?)'
        cursor = await self.db.execute(formatted_str, heights_db)
        rows = await cursor.fetchall()
        await cursor.close()
        return [HeaderBlock.from_bytes(row[0]) for row in rows]

    async def get_header_block_record(self, header_hash: bytes32) -> Optional[HeaderBlockRecord]:
        """Gets a block record from the database, if present"""
        cursor = await self.db.execute("SELECT * from header_blocks WHERE header_hash=?", (header_hash.hex(),))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            hbr = HeaderBlockRecord.from_bytes(row[4])
            return hbr
        else:
            return None

    async def get_sub_block_record(self, header_hash: bytes32) -> Optional[SubBlockRecord]:
        cursor = await self.db.execute(
            "SELECT sub_block from sub_block_records WHERE header_hash=?",
            (header_hash.hex(),),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return SubBlockRecord.from_bytes(row[0])
        return None

    async def get_sub_block_records(
        self,
    ) -> Tuple[Dict[bytes32, SubBlockRecord], Optional[bytes32]]:
        """
        Returns a dictionary with all sub blocks, as well as the header hash of the peak,
        if present.
        """
        cursor = await self.db.execute("SELECT * from sub_block_records")
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, SubBlockRecord] = {}
        peak: Optional[bytes32] = None
        for row in rows:
            header_hash = bytes.fromhex(row[0])
            ret[header_hash] = SubBlockRecord.from_bytes(row[6])
            if row[7]:
                assert peak is None  # Sanity check, only one peak
                peak = header_hash
        return ret, peak

    async def set_peak(self, header_hash: bytes32) -> None:
        cursor_1 = await self.db.execute("UPDATE sub_block_records SET is_peak=0 WHERE is_peak=1")
        await cursor_1.close()
        cursor_2 = await self.db.execute(
            "UPDATE sub_block_records SET is_peak=1 WHERE header_hash=?",
            (header_hash.hex(),),
        )
        await cursor_2.close()
        await self.db.commit()
