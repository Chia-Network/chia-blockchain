import asyncio
import logging
from abc import ABC
from typing import AsyncGenerator, Dict, List, Optional, Tuple
from bson.binary import Binary
from bson.codec_options import CodecOptions, TypeRegistry
from motor import motor_asyncio

from src.types.body import Body
from src.types.full_block import FullBlock
from src.types.header import HeaderData
from src.types.header_block import HeaderBlock
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.util.streamable import Streamable


log = logging.getLogger(__name__)


class Database(ABC):
    def __init__(self, db_name):
        loop = asyncio.get_event_loop()
        client = motor_asyncio.AsyncIOMotorClient(
            "mongodb://localhost:27017/", io_loop=loop
        )
        log.info("Connecting to mongodb database")
        self.db = client.get_database(
            db_name,
            codec_options=CodecOptions(
                type_registry=TypeRegistry(
                    fallback_encoder=lambda obj: Binary(bytes(obj))
                    if isinstance(obj, Streamable)
                    else obj
                )
            ),
        )
        log.info("Connected to mongodb database")


class FullNodeStore(Database):
    def __init__(self, db_name):
        super().__init__(db_name)

        # Stored on database
        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.full_blocks = self.db.get_collection("full_blocks")
        # Blocks received from other peers during sync, cleared after sync
        self.potential_blocks = self.db.get_collection("potential_blocks")

        # Stored in memory
        # Whether or not we are syncing
        self.sync_mode = False
        # Potential new tips that we have received from others.
        self.potential_tips: Dict[bytes32, FullBlock] = {}
        # List of all header hashes up to the tip, download up front
        self.potential_hashes: List[bytes32] = []
        # Header blocks received from other peers during sync
        self.potential_headers: Dict[uint32, HeaderBlock] = {}
        # Event to signal when header hashes are received
        self.potential_hashes_received: asyncio.Event = None
        # Event to signal when headers are received at each height
        self.potential_headers_received: Dict[uint32, asyncio.Event] = {}
        # Event to signal when blocks are received at each height
        self.potential_blocks_received: Dict[uint32, asyncio.Event] = {}
        # Blocks that we have finalized during sync, queue them up for adding after sync is done
        self.potential_future_blocks: List[FullBlock] = []
        # Current estimate of the speed of the network timelords
        self.proof_of_time_estimate_ips: uint64 = uint64(10000)
        # Our best unfinished block
        self.unfinished_blocks_leader: Tuple[uint32, uint64] = (
            uint32(0),
            uint64((1 << 64) - 1),
        )
        # Blocks which we have created, but don't have proof of space yet, old ones are cleared
        self.candidate_blocks: Dict[
            bytes32, Tuple[Body, HeaderData, ProofOfSpace, uint32]
        ] = {}
        # Blocks which are not finalized yet (no proof of time), old ones are cleared
        self.unfinished_blocks: Dict[Tuple[bytes32, uint64], FullBlock] = {}
        # Blocks which we have received but our blockchain dose not reach, old ones are cleared
        self.disconnected_blocks: Dict[bytes32, FullBlock] = {}

        # Lock
        self.lock = asyncio.Lock()  # external

    async def _clear_database(self):
        await self.full_blocks.drop()
        await self.potential_blocks.drop()

    async def add_block(self, block: FullBlock) -> None:
        header_hash = block.header_hash
        await self.full_blocks.find_one_and_update(
            {"_id": header_hash},
            {"$set": {"_id": header_hash, "block": block}},
            upsert=True,
        )

    async def get_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        query = await self.full_blocks.find_one({"_id": header_hash})
        if query is not None:
            return FullBlock.from_bytes(query["block"])
        return None

    async def get_blocks(self) -> AsyncGenerator[FullBlock, None]:
        async for query in self.full_blocks.find({}):
            yield FullBlock.from_bytes(query["block"])

    async def add_disconnected_block(self, block: FullBlock) -> None:
        self.disconnected_blocks[block.header_hash] = block

    async def get_disconnected_block_by_prev(
        self, prev_header_hash: bytes32
    ) -> Optional[FullBlock]:
        for _, block in self.disconnected_blocks.items():
            if block.prev_header_hash == prev_header_hash:
                return block
        return None

    async def get_disconnected_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.disconnected_blocks.get(header_hash, None)

    async def clear_disconnected_blocks_below(self, height: uint32) -> None:
        for key in list(self.disconnected_blocks.keys()):
            if self.disconnected_blocks[key].height < height:
                del self.disconnected_blocks[key]

    async def set_sync_mode(self, sync_mode: bool) -> None:
        self.sync_mode = sync_mode

    async def get_sync_mode(self) -> bool:
        return self.sync_mode

    async def clear_sync_info(self):
        self.potential_tips.clear()
        self.potential_headers.clear()
        await self.potential_blocks.drop()
        self.potential_blocks_received.clear()
        self.potential_future_blocks.clear()

    async def get_potential_tips_tuples(self) -> List[Tuple[bytes32, FullBlock]]:
        return list(self.potential_tips.items())

    async def add_potential_tip(self, block: FullBlock) -> None:
        self.potential_tips[block.header_hash] = block

    async def get_potential_tip(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.potential_tips.get(header_hash, None)

    def add_potential_header(self, block: HeaderBlock) -> None:
        self.potential_headers[block.height] = block

    def get_potential_header(self, height: uint32) -> Optional[HeaderBlock]:
        return self.potential_headers.get(height, None)

    def set_potential_hashes(self, potential_hashes: List[bytes32]) -> None:
        self.potential_hashes = potential_hashes

    def get_potential_hashes(self) -> List[bytes32]:
        return self.potential_hashes

    async def add_potential_block(self, block: FullBlock) -> None:
        await self.potential_blocks.find_one_and_update(
            {"_id": block.height},
            {"$set": {"_id": block.height, "block": block}},
            upsert=True,
        )

    async def get_potential_block(self, height: uint32) -> Optional[FullBlock]:
        query = await self.potential_blocks.find_one({"_id": height})
        return FullBlock.from_bytes(query["block"]) if query else None

    def set_potential_hashes_received(self, event: asyncio.Event):
        self.potential_hashes_received = event

    def get_potential_hashes_received(self) -> asyncio.Event:
        return self.potential_hashes_received

    def set_potential_headers_received(self, height: uint32, event: asyncio.Event):
        self.potential_headers_received[height] = event

    def get_potential_headers_received(self, height: uint32) -> asyncio.Event:
        return self.potential_headers_received[height]

    def set_potential_blocks_received(self, height: uint32, event: asyncio.Event):
        self.potential_blocks_received[height] = event

    def get_potential_blocks_received(self, height: uint32) -> asyncio.Event:
        return self.potential_blocks_received[height]

    async def add_potential_future_block(self, block: FullBlock):
        self.potential_future_blocks.append(block)

    async def get_potential_future_blocks(self):
        return self.potential_future_blocks

    async def add_candidate_block(
        self, pos_hash: bytes32, body: Body, header: HeaderData, pos: ProofOfSpace,
    ):
        self.candidate_blocks[pos_hash] = (body, header, pos, body.coinbase.height)

    async def get_candidate_block(
        self, pos_hash: bytes32
    ) -> Optional[Tuple[Body, HeaderData, ProofOfSpace]]:
        res = self.candidate_blocks.get(pos_hash, None)
        if res is None:
            return None
        return (res[0], res[1], res[2])

    async def clear_candidate_blocks_below(self, height: uint32) -> None:
        for key in list(self.candidate_blocks.keys()):
            if self.candidate_blocks[key][3] < height:
                del self.candidate_blocks[key]

    async def add_unfinished_block(
        self, key: Tuple[bytes32, uint64], block: FullBlock
    ) -> None:
        self.unfinished_blocks[key] = block

    async def get_unfinished_block(
        self, key: Tuple[bytes32, uint64]
    ) -> Optional[FullBlock]:
        return self.unfinished_blocks.get(key, None)

    async def get_unfinished_blocks(self) -> Dict[Tuple[bytes32, uint64], FullBlock]:
        return self.unfinished_blocks.copy()

    async def clear_unfinished_blocks_below(self, height: uint32) -> None:
        for key in list(self.unfinished_blocks.keys()):
            if self.unfinished_blocks[key].height < height:
                del self.unfinished_blocks[key]

    def set_unfinished_block_leader(self, key: Tuple[bytes32, uint64]) -> None:
        self.unfinished_blocks_leader = key

    def get_unfinished_block_leader(self) -> Tuple[bytes32, uint64]:
        return self.unfinished_blocks_leader

    async def set_proof_of_time_estimate_ips(self, estimate: uint64):
        self.proof_of_time_estimate_ips = estimate

    async def get_proof_of_time_estimate_ips(self) -> uint64:
        return self.proof_of_time_estimate_ips
