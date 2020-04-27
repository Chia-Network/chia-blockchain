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


class SyncStore:
    db: aiosqlite.Connection
    # Whether we are waiting for tips (at the start of sync) or already syncing
    waiting_for_tips: bool
    # Potential new tips that we have received from others.
    potential_tips: Dict[bytes32, FullBlock]
    # List of all header hashes up to the tip, download up front
    potential_hashes: List[bytes32]
    # Header blocks received from other peers during sync
    potential_headers: Dict[uint32, HeaderBlock]
    # Event to signal when header hashes are received
    potential_hashes_received: Optional[asyncio.Event]
    # Event to signal when headers are received at each height
    potential_headers_received: Dict[uint32, asyncio.Event]
    # Event to signal when blocks are received at each height
    potential_blocks_received: Dict[uint32, asyncio.Event]
    # Blocks that we have finalized during sync, queue them up for adding after sync is done
    potential_future_blocks: List[FullBlock]

    @classmethod
    async def create(cls, connection):
        self = cls()

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db = connection
        # Blocks received from other peers during sync, cleared after sync
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS potential_blocks(height bigint PRIMARY KEY, block blob)"
        )

        await self.db.commit()

        self.sync_mode = False
        self.waiting_for_tips = True
        self.potential_tips = {}
        self.potential_hashes = []
        self.potential_headers = {}
        self.potential_hashes_received = None
        self.potential_headers_received = {}
        self.potential_blocks_received = {}
        self.potential_future_blocks = []
        return self

    async def _clear_database(self):
        async with self.lock:
            await self.db.execute("DELETE FROM potential_blocks")
            await self.db.commit()

    async def add_potential_block(self, block: FullBlock) -> None:
        cursor = await self.db.execute(
            "INSERT OR REPLACE INTO potential_blocks VALUES(?, ?)",
            (block.height, bytes(block)),
        )
        await cursor.close()
        await self.db.commit()

    async def get_potential_block(self, height: uint32) -> Optional[FullBlock]:
        cursor = await self.db.execute(
            "SELECT * from potential_blocks WHERE height=?", (height,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return FullBlock.from_bytes(row[1])
        return None

    def set_waiting_for_tips(self, waiting_for_tips: bool) -> None:
        self.waiting_for_tips = waiting_for_tips

    def get_waiting_for_tips(self) -> bool:
        return self.waiting_for_tips

    async def clear_sync_info(self):
        self.potential_tips.clear()
        self.potential_headers.clear()
        cursor = await self.db.execute("DELETE FROM potential_blocks")
        await cursor.close()
        self.potential_blocks_received.clear()
        self.potential_future_blocks.clear()
        self.waiting_for_tips = True

    def get_potential_tips_tuples(self) -> List[Tuple[bytes32, FullBlock]]:
        return list(self.potential_tips.items())

    def add_potential_tip(self, block: FullBlock) -> None:
        self.potential_tips[block.header_hash] = block

    def get_potential_tip(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.potential_tips.get(header_hash, None)

    def add_potential_header(self, block: HeaderBlock) -> None:
        self.potential_headers[block.height] = block

    def get_potential_header(self, height: uint32) -> Optional[HeaderBlock]:
        return self.potential_headers.get(height, None)

    def clear_potential_headers(self) -> None:
        self.potential_headers.clear()

    def set_potential_hashes(self, potential_hashes: List[bytes32]) -> None:
        self.potential_hashes = potential_hashes

    def get_potential_hashes(self) -> List[bytes32]:
        return self.potential_hashes

    def set_potential_hashes_received(self, event: asyncio.Event):
        self.potential_hashes_received = event

    def get_potential_hashes_received(self) -> Optional[asyncio.Event]:
        return self.potential_hashes_received

    def set_potential_headers_received(self, height: uint32, event: asyncio.Event):
        self.potential_headers_received[height] = event

    def get_potential_headers_received(self, height: uint32) -> asyncio.Event:
        return self.potential_headers_received[height]

    def set_potential_blocks_received(self, height: uint32, event: asyncio.Event):
        self.potential_blocks_received[height] = event

    def get_potential_blocks_received(self, height: uint32) -> asyncio.Event:
        return self.potential_blocks_received[height]

    def add_potential_future_block(self, block: FullBlock):
        self.potential_future_blocks.append(block)

    def get_potential_future_blocks(self):
        return self.potential_future_blocks
