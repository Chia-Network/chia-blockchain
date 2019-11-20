import asyncio
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


class Database(ABC):
    # All databases must subclass this so that there's one client
    # Ensure mongod service is running
    loop = asyncio.get_event_loop()
    client = motor_asyncio.AsyncIOMotorClient(
        "mongodb://localhost:27017/", io_loop=loop
    )

    def __init__(self, db_name):
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


class FullNodeStore(Database):
    def __init__(self, db_name):
        super().__init__(db_name)

        # Stored on database
        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.full_blocks = self.db.get_collection("full_blocks")
        # Potential new tips that we have received from others.
        self.potential_tips = self.db.get_collection("potential_tips")
        # Header blocks received from other peers during sync
        self.potential_headers = self.db.get_collection("potential_headers")
        # Blocks received from other peers during sync
        self.potential_blocks = self.db.get_collection("potential_blocks")
        # Blocks which we have created, but don't have proof of space yet
        self.candidate_blocks = self.db.get_collection("candidate_blocks")
        # Blocks which are not finalized yet (no proof of time)
        self.unfinished_blocks = self.db.get_collection("unfinished_blocks")
        # Whether or not we are syncing
        self.sync_mode = self.db.get_collection("sync_mode")

        # Stored in memory
        # Our best unfinished block
        self.unfinished_blocks_leader: Tuple[uint32, uint64] = (
            uint32(0),
            uint64(9999999999),
        )
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
        await self.potential_tips.drop()
        await self.potential_headers.drop()
        await self.potential_blocks.drop()
        await self.candidate_blocks.drop()
        await self.unfinished_blocks.drop()
        await self.sync_mode.drop()

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

    async def set_sync_mode(self, sync_mode: bool) -> None:
        await self.sync_mode.update_one(
            {"_id": 0}, {"$set": {"_id": 0, "value": sync_mode}}, upsert=True
        )

    async def get_sync_mode(self) -> bool:
        query = await self.sync_mode.find_one({"_id": 0})
        return query.get("value", True) if query else True

    async def _set_default_sync_mode(self, sync_mode):
        query = await self.sync_mode.find_one({"_id": 0})
        if query is None:
            await self.set_sync_mode(sync_mode)

    async def clear_sync_info(self):
        await self.potential_tips.drop()
        await self.potential_headers.drop()
        await self.potential_blocks.drop()
        self.potential_blocks_received.clear()
        self.potential_future_blocks.clear()

    async def get_potential_tips_tuples(self) -> List[Tuple[bytes32, FullBlock]]:
        ans = []
        async for query in self.potential_tips.find({}):
            if query and "block" in query:
                block = FullBlock.from_bytes(query["block"])
            else:
                block = None
            ans.append((bytes32(query["_id"]), block))
        return ans

    async def add_potential_tip(self, block: FullBlock) -> None:
        action = {"$set": {"block": block}}
        await self.potential_tips.find_one_and_update(
            {"_id": block.header_hash}, action, upsert=True
        )

    async def get_potential_tip(self, header_hash: bytes32) -> Optional[FullBlock]:
        query = await self.potential_tips.find_one({"_id": header_hash})
        block = query.get("block", None) if query else None
        return FullBlock.from_bytes(block) if block else None

    async def add_potential_header(self, block: HeaderBlock) -> None:
        await self.potential_headers.find_one_and_update(
            {"_id": block.height},
            {"$set": {"_id": block.height, "header": block}},
            upsert=True,
        )

    async def get_potential_header(self, height: uint32) -> Optional[HeaderBlock]:
        query = await self.potential_headers.find_one({"_id": height})
        return HeaderBlock.from_bytes(query["header"]) if query else None

    async def add_potential_block(self, block: FullBlock) -> None:
        await self.potential_blocks.find_one_and_update(
            {"_id": block.height},
            {"$set": {"_id": block.height, "block": block}},
            upsert=True,
        )

    async def get_potential_block(self, height: uint32) -> Optional[FullBlock]:
        query = await self.potential_blocks.find_one({"_id": height})
        return FullBlock.from_bytes(query["block"]) if query else None

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
