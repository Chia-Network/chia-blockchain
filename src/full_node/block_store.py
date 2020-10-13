import logging
import aiosqlite
from typing import Dict, List, Optional

from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.hash import std_hash
from src.util.ints import uint32, uint128
from src.full_node.sub_block_record import SubBlockRecord

log = logging.getLogger(__name__)


class BlockStore:
    db: aiosqlite.Connection

    @classmethod
    async def create(cls, connection: aiosqlite.Connection):
        self = cls()

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db = connection
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS blocks(height bigint, header_hash text PRIMARY KEY, block blob)"
        )

        # Sub blocks
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS sub_blocks(header_hash "
            "text PRIMARY KEY, prev_hash text, height bigint, weight bigint, total_iters text"
            "blob, is_lca tinyint, is_tip tinyint)"
        )

        # Height index so we can look up in order of height for sync purposes
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS full_block_height on blocks(height)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS sub_block_height on sub_blocks(height)"
        )

        await self.db.execute("CREATE INDEX IF NOT EXISTS hh on sub_blocks(header_hash)")
        await self.db.commit()

        return self

    async def add_block(self, block: FullBlock) -> None:
        assert block.proof_of_time is not None
        cursor_1 = await self.db.execute(
            "INSERT OR REPLACE INTO blocks VALUES(?, ?, ?)",
            (block.height, block.header_hash.hex(), bytes(block)),
        )
        await cursor_1.close()
        proof_hash = std_hash(
            block.proof_of_space.get_hash() + block.proof_of_time.output.get_hash()
        )
        cursor_2 = await self.db.execute(
            "INSERT OR REPLACE INTO sub_blocks VALUES(?, ?, ?, ?, ?)",
            (
                block.header_hash.hex(),
                block.prev_header_hash.hex(),
                block.height,
                block.weight.to_bytes(128/8, "big", signed=False).hex(),
                block.total_iters.to_bytes(128/8, "big", signed=False).hex(),
            ),
        )
        await cursor_2.close()
        await self.db.commit()

    async def get_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        cursor = await self.db.execute(
            "SELECT block from blocks WHERE header_hash=?", (header_hash.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return FullBlock.from_bytes(row[0])
        return None

    async def get_blocks_at(self, heights: List[uint32]) -> List[FullBlock]:
        if len(heights) == 0:
            return []

        heights_db = tuple(heights)
        formatted_str = f'SELECT block from blocks WHERE height in ({"?," * (len(heights_db) - 1)}?)'
        cursor = await self.db.execute(formatted_str, heights_db)
        rows = await cursor.fetchall()
        await cursor.close()
        return [FullBlock.from_bytes(row[0]) for row in rows]

    async def get_sub_blocks(self) -> Dict[bytes32, SubBlockRecord]:
        cursor = await self.db.execute("SELECT * from sub_blocks")
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, SubBlockRecord] = {}
        for row in rows:
            header_hash = bytes.fromhex(row[0])
            prev_hash = bytes.fromhex(row[1])
            weight = uint128(int.from_bytes(bytes.fromhex(row[3]), "big", signed=False))
            total_iters = uint128(int.from_bytes(bytes.fromhex(row[4]), "big", signed=False))
            ret[header_hash] = SubBlockRecord(header_hash, prev_hash, row[2], weight, total_iters)
        return ret
