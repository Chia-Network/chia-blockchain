import logging
import aiosqlite
from typing import Dict, List, Optional

from src.types.full_block import FullBlock
from src.types.header import Header
from src.types.sized_bytes import bytes32
from src.util.hash import std_hash
from src.util.ints import uint32

log = logging.getLogger(__name__)


class BlockStore:
    db: aiosqlite.Connection

    @classmethod
    async def create(cls, connection):
        self = cls()

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db = connection
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS blocks(height bigint, header_hash text PRIMARY KEY, block blob)"
        )

        # Headers
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS headers(height bigint, header_hash "
            "text PRIMARY KEY, proof_hash text, header blob, is_lca tinyint, is_tip tinyint)"
        )

        # Height index so we can look up in order of height for sync purposes
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS block_height on blocks(height)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS header_height on headers(height)"
        )

        # is_lca and is_tip index to quickly find tips and lca
        await self.db.execute("CREATE INDEX IF NOT EXISTS lca on headers(is_lca)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS lca on headers(is_tip)")
        await self.db.commit()

        return self

    async def get_lca(self) -> Optional[Header]:
        cursor = await self.db.execute("SELECT header from headers WHERE is_lca=1")
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return Header.from_bytes(row[0])
        return None

    async def set_lca(self, header_hash: bytes32) -> None:
        cursor_1 = await self.db.execute("UPDATE headers SET is_lca=0")
        await cursor_1.close()
        cursor_2 = await self.db.execute(
            "UPDATE headers SET is_lca=1 WHERE header_hash=?", (header_hash.hex(),)
        )
        await cursor_2.close()
        await self.db.commit()

    async def get_tips(self) -> List[bytes32]:
        cursor = await self.db.execute("SELECT header from headers WHERE is_tip=1")
        rows = await cursor.fetchall()
        await cursor.close()
        return [Header.from_bytes(row[0]) for row in rows]

    async def set_tips(self, header_hashes: List[bytes32]) -> None:
        cursor_1 = await self.db.execute("UPDATE headers SET is_tip=0")
        await cursor_1.close()
        tips_db = tuple([h.hex() for h in header_hashes])

        formatted_str = f'UPDATE headers SET is_tip=1 WHERE header_hash in ({"?," * (len(tips_db) - 1)}?)'
        cursor_2 = await self.db.execute(formatted_str, tips_db)
        await cursor_2.close()
        await self.db.commit()

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
            ("INSERT OR REPLACE INTO headers VALUES(?, ?, ?, ?, 0, 0)"),
            (
                block.height,
                block.header_hash.hex(),
                proof_hash.hex(),
                bytes(block.header),
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

    async def get_headers(self) -> Dict[bytes32, Header]:
        cursor = await self.db.execute("SELECT header_hash, header from headers")
        rows = await cursor.fetchall()
        await cursor.close()
        return {bytes.fromhex(row[0]): Header.from_bytes(row[1]) for row in rows}

    async def get_proof_hashes(self) -> Dict[bytes32, bytes32]:
        cursor = await self.db.execute("SELECT header_hash, proof_hash from headers")
        rows = await cursor.fetchall()
        await cursor.close()
        return {bytes.fromhex(row[0]): bytes.fromhex(row[1]) for row in rows}
