import asyncio
import logging
import aiosqlite
from typing import Dict, List, Optional, Tuple

from blspy import PublicKey
from src.types.body import Body
from src.types.full_block import FullBlock
from src.types.header import HeaderData
from src.types.header_block import HeaderBlock, SmallHeaderBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64

log = logging.getLogger(__name__)


class FullNodeStore:
    db_name: str
    db: aiosqlite.Connection
    # Whether or not we are syncing
    sync_mode: bool
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
    # Current estimate of the speed of the network timelords
    proof_of_time_estimate_ips: uint64
    # Our best unfinished block
    unfinished_blocks_leader: Tuple[uint32, uint64]
    # Blocks which we have created, but don't have proof of space yet, old ones are cleared
    candidate_blocks: Dict[bytes32, Tuple[Body, HeaderData, ProofOfSpace, uint32]]
    # Blocks which are not finalized yet (no proof of time), old ones are cleared
    unfinished_blocks: Dict[Tuple[bytes32, uint64], FullBlock]
    # Header hashes of unfinished blocks that we have seen recently
    seen_unfinished_blocks: set
    # Blocks which we have received but our blockchain does not reach, old ones are cleared
    disconnected_blocks: Dict[bytes32, FullBlock]
    # Lock
    lock: asyncio.Lock

    @classmethod
    async def create(cls, db_name: str):
        self = cls()
        self.db_name = db_name

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db = await aiosqlite.connect(self.db_name)
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS blocks(height bigint, header_hash text PRIMARY KEY, block blob)"
        )

        # Blocks received from other peers during sync, cleared after sync
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS potential_blocks(height bigint PRIMARY KEY, block blob)"
        )

        # Headers
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS small_header_blocks(height bigint, header_hash "
            "text PRIMARY KEY, pool_pk text, small_header_block blob)"
        )

        # Height index so we can look up in order of height for sync purposes
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS block_height on blocks(height)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS small_header__block_height on small_header_blocks(height)"
        )

        await self.db.commit()

        self.sync_mode = False
        self.potential_tips = {}
        self.potential_hashes = []
        self.potential_headers = {}
        self.potential_hashes_received = None
        self.potential_headers_received = {}
        self.potential_blocks_received = {}
        self.potential_future_blocks = []
        self.proof_of_time_estimate_ips = uint64(10000)
        self.unfinished_blocks_leader = (
            uint32(0),
            uint64((1 << 64) - 1),
        )
        self.candidate_blocks = {}
        self.unfinished_blocks = {}
        self.seen_unfinished_blocks = set()
        self.disconnected_blocks = {}
        self.lock = asyncio.Lock()  # external
        return self

    async def close(self):
        await self.db.close()

    async def _clear_database(self):
        await self.db.execute("DELETE FROM blocks")
        await self.db.execute("DELETE FROM potential_blocks")
        await self.db.execute("DELETE FROM small_header_blocks")
        await self.db.commit()

    async def add_block(self, block: FullBlock) -> None:
        cursor_1 = await self.db.execute(
            "INSERT OR REPLACE INTO blocks VALUES(?, ?, ?)",
            (block.height, block.header_hash.hex(), bytes(block)),
        )
        await cursor_1.close()
        assert block.header_block.challenge is not None

        cursor_2 = await self.db.execute(
            ("INSERT OR REPLACE INTO small_header_blocks VALUES(?, ?, ?, ?)"),
            (
                block.height,
                block.header_hash.hex(),
                bytes(block.header_block.proof_of_space.pool_pubkey).hex(),
                bytes(block.header_block.to_small()),
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

    async def get_header_blocks_by_hash(
        self, header_hashes: List[bytes32]
    ) -> List[HeaderBlock]:
        if len(header_hashes) == 0:
            return []
        header_hashes_db = tuple(h.hex() for h in header_hashes)
        formatted_str = f'SELECT * from blocks WHERE header_hash in ({"?," * (len(header_hashes_db) - 1)}?)'
        cursor = await self.db.execute(formatted_str, header_hashes_db)
        rows = await cursor.fetchall()
        await cursor.close()
        header_blocks: List[HeaderBlock] = []
        for row in rows:
            header_blocks.append(FullBlock.from_bytes(row[2]).header_block)

        # Sorts the passed in header hashes by hash, with original index
        header_hashes_sorted = sorted(
            enumerate(header_hashes), key=lambda pair: pair[1]
        )

        # Sorts the fetched header blocks by hash
        header_blocks_sorted = sorted(header_blocks, key=lambda hb: hb.header_hash)

        # Combine both and sort by the original indeces
        combined = sorted(
            zip(header_hashes_sorted, header_blocks_sorted), key=lambda pair: pair[0][0]
        )

        # Return only the header blocks in the original order
        return [pair[1] for pair in combined]

    async def get_small_header_blocks(self) -> List[SmallHeaderBlock]:
        cursor = await self.db.execute("SELECT * from small_header_blocks")
        rows = await cursor.fetchall()
        await cursor.close()
        return [SmallHeaderBlock.from_bytes(row[3]) for row in rows]

    async def get_pool_pks_hack(self) -> List[Tuple[uint32, PublicKey]]:
        # TODO: this API call is a hack to allow us to see block winners. Replace with coin/UTXU set.
        cursor = await self.db.execute("SELECT * from small_header_blocks")
        rows = await cursor.fetchall()
        return [
            (
                SmallHeaderBlock.from_bytes(row[3]).height,
                PublicKey.from_bytes(bytes.fromhex(row[2])),
            )
            for row in rows
        ]

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

    def add_disconnected_block(self, block: FullBlock) -> None:
        self.disconnected_blocks[block.header_hash] = block

    def get_disconnected_block_by_prev(
        self, prev_header_hash: bytes32
    ) -> Optional[FullBlock]:
        for _, block in self.disconnected_blocks.items():
            if block.prev_header_hash == prev_header_hash:
                return block
        return None

    def get_disconnected_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.disconnected_blocks.get(header_hash, None)

    def clear_disconnected_blocks_below(self, height: uint32) -> None:
        for key in list(self.disconnected_blocks.keys()):
            if self.disconnected_blocks[key].height < height:
                del self.disconnected_blocks[key]

    def set_sync_mode(self, sync_mode: bool) -> None:
        self.sync_mode = sync_mode

    def get_sync_mode(self) -> bool:
        return self.sync_mode

    async def clear_sync_info(self):
        self.potential_tips.clear()
        self.potential_headers.clear()
        cursor = await self.db.execute("DELETE FROM potential_blocks")
        await cursor.close()
        self.potential_blocks_received.clear()
        self.potential_future_blocks.clear()

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

    async def add_candidate_block(
        self,
        pos_hash: bytes32,
        body: Body,
        header: HeaderData,
        pos: ProofOfSpace,
        height: int = 0,
    ):
        self.candidate_blocks[pos_hash] = (body, header, pos, height)  # type: ignore # noqa

    def get_candidate_block(
        self, pos_hash: bytes32
    ) -> Optional[Tuple[Body, HeaderData, ProofOfSpace]]:
        res = self.candidate_blocks.get(pos_hash, None)
        if res is None:
            return None
        return (res[0], res[1], res[2])

    def clear_candidate_blocks_below(self, height: uint32) -> None:
        for key in list(self.candidate_blocks.keys()):
            if self.candidate_blocks[key][3] < height:
                del self.candidate_blocks[key]

    def add_unfinished_block(
        self, key: Tuple[bytes32, uint64], block: FullBlock
    ) -> None:
        self.unfinished_blocks[key] = block

    def get_unfinished_block(self, key: Tuple[bytes32, uint64]) -> Optional[FullBlock]:
        return self.unfinished_blocks.get(key, None)

    def seen_unfinished_block(self, header_hash: bytes32) -> bool:
        if header_hash in self.seen_unfinished_blocks:
            return True
        self.seen_unfinished_blocks.add(header_hash)
        return False

    def clear_seen_unfinished_blocks(self) -> None:
        self.seen_unfinished_blocks.clear()

    def get_unfinished_blocks(self) -> Dict[Tuple[bytes32, uint64], FullBlock]:
        return self.unfinished_blocks.copy()

    def clear_unfinished_blocks_below(self, height: uint32) -> None:
        for key in list(self.unfinished_blocks.keys()):
            if self.unfinished_blocks[key].height < height:
                del self.unfinished_blocks[key]

    def set_unfinished_block_leader(self, key: Tuple[bytes32, uint64]) -> None:
        self.unfinished_blocks_leader = key

    def get_unfinished_block_leader(self) -> Tuple[bytes32, uint64]:
        return self.unfinished_blocks_leader

    def set_proof_of_time_estimate_ips(self, estimate: uint64):
        self.proof_of_time_estimate_ips = estimate

    def get_proof_of_time_estimate_ips(self) -> uint64:
        return self.proof_of_time_estimate_ips
