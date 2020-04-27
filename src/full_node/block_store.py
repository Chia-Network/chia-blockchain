import asyncio
import logging
import aiosqlite
from typing import Dict, List, Optional, Tuple

from src.types.program import Program
from src.types.full_block import FullBlock
from src.types.header import HeaderData, Header
from src.types.header_block import HeaderBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.hash import std_hash
from src.util.ints import uint32, uint64

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
            "text PRIMARY KEY, proof_hash text, header blob)"
        )

        # LCA
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS lca(header_hash text PRIMARY KEY)"
        )

        # Height index so we can look up in order of height for sync purposes
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS block_height on blocks(height)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS header_height on headers(height)"
        )

        await self.db.commit()

        return self

    async def _clear_database(self):
        async with self.lock:
            await self.db.execute("DELETE FROM blocks")
            await self.db.execute("DELETE FROM headers")
            await self.db.commit()

    async def get_lca(self) -> Optional[bytes32]:
        cursor = await self.db.execute("SELECT * from lca")
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return bytes32(bytes.fromhex(row[0]))
        return None

    async def set_lca(self, header_hash: bytes32) -> None:
        await self.db.execute("DELETE FROM lca")
        cursor_1 = await self.db.execute(
            "INSERT OR REPLACE INTO lca VALUES(?)", (header_hash.hex(),)
        )
        await cursor_1.close()
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
            ("INSERT OR REPLACE INTO headers VALUES(?, ?, ?, ?)"),
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
            "SELECT * from blocks WHERE header_hash=?", (header_hash.hex(),)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return FullBlock.from_bytes(row[2])
        return None

    async def get_blocks_at(self, heights: List[uint32]) -> List[FullBlock]:
        if len(heights) == 0:
            return []

        heights_db = tuple(heights)
        formatted_str = (
            f'SELECT * from blocks WHERE height in ({"?," * (len(heights_db) - 1)}?)'
        )
        cursor = await self.db.execute(formatted_str, heights_db)
        rows = await cursor.fetchall()
        await cursor.close()
        blocks: List[FullBlock] = []
        for row in rows:
            blocks.append(FullBlock.from_bytes(row[2]))
        return blocks

    async def get_headers(self) -> List[Header]:
        cursor = await self.db.execute("SELECT * from headers")
        rows = await cursor.fetchall()
        await cursor.close()
        return [Header.from_bytes(row[3]) for row in rows]

    async def get_proof_hashes(self) -> Dict[bytes32, bytes32]:
        cursor = await self.db.execute("SELECT header_hash, proof_hash from headers")
        rows = await cursor.fetchall()
        await cursor.close()
        return {bytes.fromhex(row[0]): bytes.fromhex(row[1]) for row in rows}
