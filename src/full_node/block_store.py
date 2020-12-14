import logging
import aiosqlite
from typing import Dict, List, Optional, Tuple

from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from src.consensus.sub_block_record import SubBlockRecord

log = logging.getLogger(__name__)


class BlockStore:
    db: aiosqlite.Connection

    @classmethod
    async def create(cls, connection: aiosqlite.Connection):
        self = cls()

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db = connection
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS full_blocks(header_hash text PRIMARY KEY, sub_height bigint, height bigint, is_block tinyint, block blob)"
        )

        # Sub block records
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS sub_block_records(header_hash "
            "text PRIMARY KEY, prev_hash text, sub_height bigint, height bigint, weight bigint, total_iters text,"
            "sub_block blob, is_peak tinyint, is_block tinyint)"
        )

        # Height index so we can look up in order of height for sync purposes
        await self.db.execute("CREATE INDEX IF NOT EXISTS full_block_sub_height on full_blocks(sub_height)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS full_block_height on full_blocks(height)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS is_block on full_blocks(is_block)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS sub_block_height on sub_block_records(height)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS sub_block_sub_height on sub_block_records(sub_height)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS hh on sub_block_records(header_hash)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS peak on sub_block_records(is_peak)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS is_block on sub_block_records(is_block)")

        await self.db.commit()

        return self

    async def add_full_block(self, block: FullBlock, sub_block: SubBlockRecord) -> None:
        if block.is_block():
            height = block.height
        else:
            height = sub_block.prev_block_height + 1

        cursor_1 = await self.db.execute("INSERT OR REPLACE INTO full_blocks VALUES(?, ?, ?, ?, ?)",
                       (block.header_hash.hex(), block.sub_block_height, height, int(block.is_block()), bytes(block)),
                    )

        await cursor_1.close()
        #  proof_hash = std_hash(block.proof_of_space.get_hash() + block.proof_of_time.output.get_hash())
        weight = block.weight.to_bytes(128 // 8, "big", signed=False).hex()
        total_iters = block.total_iters.to_bytes(128 // 8, "big", signed=False).hex()

        cursor_2 = await self.db.execute(f"INSERT OR REPLACE INTO sub_block_records VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
             (block.header_hash.hex(), block.prev_header_hash.hex(), block.sub_block_height, height,
              weight, total_iters, bytes(sub_block), False, block.is_block())
        )
        await cursor_2.close()
        await self.db.commit()

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        cursor = await self.db.execute("SELECT block from full_blocks WHERE header_hash=?", (header_hash.hex(),))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return FullBlock.from_bytes(row[0])
        return None

    async def get_full_blocks_at(self, sub_heights: List[uint32]) -> List[FullBlock]:
        if len(sub_heights) == 0:
            return []

        heights_db = tuple(sub_heights)
        formatted_str = f'SELECT block from full_blocks WHERE sub_height in ({"?," * (len(heights_db) - 1)}?)'
        cursor = await self.db.execute(formatted_str, heights_db)
        rows = await cursor.fetchall()
        await cursor.close()
        return [FullBlock.from_bytes(row[0]) for row in rows]

    async def get_sub_block_record(self, header_hash: bytes32) -> Optional[SubBlockRecord]:
        cursor = await self.db.execute(
            "SELECT sub_block from sub_block_records WHERE header_hash=?", (header_hash.hex(),)
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
            "UPDATE sub_block_records SET is_peak=1 WHERE header_hash=?", (header_hash.hex(),)
        )
        await cursor_2.close()
        await self.db.commit()
