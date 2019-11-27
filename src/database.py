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
    # All databases must subclass this so that there's one client
    # Ensure mongod service is running
    loop = asyncio.get_event_loop()
    client = motor_asyncio.AsyncIOMotorClient(
        "mongodb://localhost:27017/", io_loop=loop
    )

    def __init__(self, db_name):
        log.info("Connecting to mongodb database")
        self.db = Database.client.get_database(
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
        # Blocks received from other peers during sync
        self.potential_blocks = self.db.get_collection("potential_blocks")
        # Blocks which we have created, but don't have proof of space yet
        self.candidate_blocks = self.db.get_collection("candidate_blocks")
        # Blocks which are not finalized yet (no proof of time)
        self.unfinished_blocks = self.db.get_collection("unfinished_blocks")
        # Blocks which we have received but our blockchain dose not reach
        self.disconnected_blocks = self.db.get_collection("unfinished_blocks")

        # Stored in memory
        # Whether or not we are syncing
        self.sync_mode = False
        # Potential new tips that we have received from others.
        self.potential_tips: Dict[bytes32, FullBlock] = {}

        # Header blocks received from other peers during sync
        self.potential_headers: Dict[uint32, HeaderBlock] = {}
        # Our best unfinished block
        self.unfinished_blocks_leader: Tuple[uint32, uint64] = (
            uint32(0),
            uint64(9999999999),
        )
        # Event to signal when headers are received at each height
        self.potential_headers_received: Dict[uint32, asyncio.Event] = {}
        # Event to signal when blocks are received at each height
        self.potential_blocks_received: Dict[uint32, asyncio.Event] = {}
        # Blocks that we have finalized during sync, queue them up for adding after sync is done
        self.potential_future_blocks: List[FullBlock] = []
        # Current estimate of the speed of the network timelords
        self.proof_of_time_estimate_ips: uint64 = uint64(3000)

        # Lock
        self.lock = asyncio.Lock()  # external

    async def _clear_database(self):
        await self.full_blocks.drop()
        await self.potential_blocks.drop()
        await self.candidate_blocks.drop()
        await self.unfinished_blocks.drop()
        await self.disconnected_blocks.drop()

    async def save_block(self, block: FullBlock) -> None:
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

    async def save_disconnected_block(self, block: FullBlock) -> None:
        prev_header_hash = block.prev_header_hash
        await self.disconnected_blocks.find_one_and_update(
            {"_id": prev_header_hash},
            {"$set": {"_id": prev_header_hash, "block": block}},
            upsert=True,
        )

    async def get_disconnected_block(
        self, prev_header_hash: bytes32
    ) -> Optional[FullBlock]:
        query = await self.disconnected_blocks.find_one({"_id": prev_header_hash})
        if query is not None:
            return FullBlock.from_bytes(query["block"])
        return None

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

    async def add_potential_header(self, block: HeaderBlock) -> None:
        self.potential_headers[block.height] = block

    async def get_potential_header(self, height: uint32) -> Optional[HeaderBlock]:
        return self.potential_headers.get(height, None)

    async def add_potential_block(self, block: FullBlock) -> None:
        await self.potential_blocks.find_one_and_update(
            {"_id": block.height},
            {"$set": {"_id": block.height, "block": block}},
            upsert=True,
        )

    async def get_potential_block(self, height: uint32) -> Optional[FullBlock]:
        query = await self.potential_blocks.find_one({"_id": height})
        return FullBlock.from_bytes(query["block"]) if query else None

    async def set_potential_headers_received(
        self, height: uint32, event: asyncio.Event
    ):
        self.potential_headers_received[height] = event

    async def get_potential_headers_received(self, height: uint32) -> asyncio.Event:
        return self.potential_headers_received[height]

    async def set_potential_blocks_received(self, height: uint32, event: asyncio.Event):
        self.potential_blocks_received[height] = event

    async def get_potential_blocks_received(self, height: uint32) -> asyncio.Event:
        return self.potential_blocks_received[height]

    async def add_potential_future_block(self, block: FullBlock):
        self.potential_future_blocks.append(block)

    async def get_potential_future_blocks(self):
        return self.potential_future_blocks

    async def add_candidate_block(
        self, pos_hash: bytes32, body: Body, header: HeaderData, pos: ProofOfSpace,
    ):
        await self.candidate_blocks.find_one_and_update(
            {"_id": pos_hash},
            {"$set": {"_id": pos_hash, "body": body, "header": header, "pos": pos}},
            upsert=True,
        )

    async def get_candidate_block(
        self, pos_hash: bytes32
    ) -> Optional[Tuple[Body, HeaderData, ProofOfSpace]]:
        query = await self.candidate_blocks.find_one({"_id": pos_hash})
        if not query:
            return None
        return (
            Body.from_bytes(query["body"]),
            HeaderData.from_bytes(query["header"]),
            ProofOfSpace.from_bytes(query["pos"]),
        )

    async def add_unfinished_block(
        self, key: Tuple[bytes32, uint64], block: FullBlock
    ) -> None:
        code = ((int.from_bytes(key[0], "big") << 64) + key[1]).to_bytes(40, "big")
        await self.unfinished_blocks.find_one_and_update(
            {"_id": code}, {"$set": {"_id": code, "block": block}}, upsert=True
        )

    async def get_unfinished_block(
        self, key: Tuple[bytes32, uint64]
    ) -> Optional[FullBlock]:
        code = ((int.from_bytes(key[0], "big") << 64) + key[1]).to_bytes(40, "big")
        query = await self.unfinished_blocks.find_one({"_id": code})
        return FullBlock.from_bytes(query["block"]) if query else None

    async def get_unfinished_blocks(self) -> Dict[Tuple[bytes32, uint64], FullBlock]:
        d = {}
        async for document in self.unfinished_blocks.find({}):
            challenge_hash = document["_id"][:32]
            iters = uint64(int.from_bytes(document["_id"][32:], byteorder="big"))
            d[(challenge_hash, iters)] = FullBlock.from_bytes(document["block"])
        return d

    def set_unfinished_block_leader(self, key: Tuple[bytes32, uint64]) -> None:
        self.unfinished_blocks_leader = key

    def get_unfinished_block_leader(self) -> Tuple[bytes32, uint64]:
        return self.unfinished_blocks_leader

    async def set_proof_of_time_estimate_ips(self, estimate: uint64):
        self.proof_of_time_estimate_ips = estimate

    async def get_proof_of_time_estimate_ips(self) -> uint64:
        return self.proof_of_time_estimate_ips
