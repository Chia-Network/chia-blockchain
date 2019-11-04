from abc import ABC
from typing import Optional, Tuple, AsyncGenerator
import asyncio
import motor.motor_asyncio as maio
from src.types.proof_of_space import ProofOfSpace
from src.types.header import HeaderData
from src.types.header_block import HeaderBlock
from src.types.body import Body
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.db.codecs import codec_options
import subprocess

class Database(ABC):
    # All databases must subclass this so that there's one client
    loop = asyncio.get_event_loop()
    subprocess.run("mongod", stdout=subprocess.PIPE)  # Ensure mongod service is running
    client = maio.AsyncIOMotorClient("mongodb://localhost:27017/", io_loop=loop)

    def __init__(self, db_name):
        # self.lock = asyncio.Lock()
        self.db = Database.client.get_database(db_name, codec_options=codec_options)


class FullNodeStore(Database):
    def __init__(self, db_name):
        super().__init__(db_name)

        # Stored on database
        getc = self.db.get_collection
        self.full_blocks = getc("full_blocks")
        self.potential_heads = getc("potential_heads")
        self.potential_trunks = getc("potential_trunks")
        self.potential_blocks = getc("potential_blocks")
        self.candidate_blocks = getc("candidate_blocks")
        self.unfinished_blocks = getc("unfinished_blocks")
        self.unfinished_blocks_leader = getc("unfinished_blocks_leader")
        self.sync_mode = getc("sync_mode")

        # Stored on memory
        self.potential_blocks_received: Dict[uint32, Event] = {}
        self.proof_of_time_estimate_ips: uint64 = uint64(3000)

        # Lock
        self.lock = asyncio.Lock()  # external


    async def _clear_database(self):
        await self.full_blocks.drop()
        await self.potential_heads.drop()
        await self.potential_headers.drop()
        await self.potential_blocks.drop()
        await self.candidate_blocks.drop()
        await self.unfinished_blocks.drop()
        await self.unfinished_blocks_leader.drop()
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
        await self.potential_heads.drop()
        await self.potential_headers.drop()
        await self.potential_blocks.drop()

    async def get_potential_heads_number(self) -> int:
        return await self.potential_heads.count_documents({})

    async def get_potential_heads_tuples(self) -> AsyncGenerator[Tuple[bytes32, FullBlock], None]:
        async for query in self.potential_heads.find({}):
            if query and "block" in query:
                block = FullBlock.from_bytes(query["block"])
            else:
                block = None
            yield bytes32(query["_id"]), block

    async def add_potential_head(
        self, header_hash: bytes32, block: Optional[FullBlock] = None
    ) -> None:
        action = {"$set": {"block": block} if block else {"_id": header_hash}}
        await self.potential_heads.find_one_and_update(
            {"_id": header_hash}, action, upsert=True
        )

    async def get_potential_head(self, header_hash: bytes32) -> Optional[FullBlock]:
        query = await self.potential_heads.find_one({"_id": header_hash})
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

    async def add_candidate_block(
        self,
        pos_hash: bytes32,
        body: Body,
        header: HeaderData,
        pos: ProofOfSpace,
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

    async def set_unfinished_block_leader(self, key: Tuple[bytes32, uint64]) -> None:
        await self.unfinished_blocks_leader.find_one_and_update(
            {"_id": 0},
            {"$set": {"_id": 0, "header": key[0], "iters": key[1]}},
            upsert=True,
        )

    async def get_unfinished_block_leader(self) -> Optional[Tuple[bytes32, uint64]]:
        query = await self.unfinished_blocks_leader.find_one({"_id": 0})
        return (query["header"], query["iters"]) if query else None

    async def set_proof_of_time_estimate_ips(self, estimate: uint64):
        self.proof_of_time_estimate_ips = estimate

    async def get_proof_of_time_estimate_ips(self) -> uint64:
        return self.proof_of_time_estimate_ips


# TODO: remove below when tested better
if __name__ == "__main__":

    async def tests():
        print("started testing")
        db = FullNodeStore("test3")
        await db._clear_database()

        from src.consensus.constants import constants

        genesis = FullBlock.from_bytes(constants["GENESIS_BLOCK"])

        # Save/get block
        await db.save_block(genesis)
        assert genesis == await db.get_block(genesis.header_hash)

        # Save/get sync
        for sync_mode in (False, True):
            await db.set_sync_mode(sync_mode)
            assert sync_mode == await db.get_sync_mode()

        # clear sync info
        await db.clear_sync_info()
        assert await db.get_potential_heads_number() == 0

        # add/get potential head, get potential heads num
        await db.add_potential_head(genesis.header_hash)
        assert await db.get_potential_heads_number() == 1
        await db.add_potential_head(genesis.header_hash, genesis)
        assert await db.get_potential_heads_number() == 1
        assert genesis == await db.get_potential_head(genesis.header_hash)

        # add/get potential header
        header = genesis.header_block
        await db.add_potential_header(header)
        assert await db.get_potential_header(genesis.height) == header

        # Add potential block
        await db.add_potential_block(genesis)
        assert genesis == await db.get_potential_block(uint32(0))

        # Add/get candidate block
        assert await db.get_candidate_block(0) is None
        partial = (
            genesis.body,
            genesis.header_block.header.data,
            genesis.header_block.proof_of_space,
        )
        await db.add_candidate_block(genesis.header_hash, *partial)
        assert await db.get_candidate_block(genesis.header_hash) == partial

        # Add/get unfinished block
        key = (genesis.header_hash, uint64(1000))
        assert await db.get_unfinished_block(key) is None
        await db.add_unfinished_block(key, genesis)
        assert await db.get_unfinished_block(key) == genesis

        # Set/get unf block leader
        assert await db.get_unfinished_block_leader() is None
        await db.set_unfinished_block_leader(key)
        assert await db.get_unfinished_block_leader() == key

        print("done testing")

    #Database.loop.run_until_complete(tests())
