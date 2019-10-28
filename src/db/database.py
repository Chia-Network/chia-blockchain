from abc import ABC
from typing import Optional, Tuple
import asyncio
import motor.motor_asyncio as maio
from src.types.proof_of_space import ProofOfSpace
from src.types.block_header import BlockHeaderData
from src.types.trunk_block import TrunkBlock
from src.types.block_body import BlockBody
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.db.codecs import codec_options


class Database(ABC):
    # After installing mongoDB, run it on the command line with "$mongod" first.
    # All databases must subclass this so that there's one client
    loop = asyncio.get_event_loop()
    client = maio.AsyncIOMotorClient("mongodb://localhost:27017/", io_loop=loop)

    def __init__(self, db_name):
        # self.lock = asyncio.Lock()
        self.db = Database.client.get_database(db_name, codec_options=codec_options)


class FullNodeDatabase(Database):
    def __init__(self, db_name):
        super().__init__(db_name)
        """  
Implicit collection schemas:
# Every field is stored as Binary (BinData) unless native int etc.
# (NOTE THAT _id 's are not ObjectId type!)

full_blocks = {_id: bytes32, block: FullBlock}
potential_heads = {_id: bytes32, value: int}
potential_heads_full_blocks = {_id: bytes32, block: FullBlock}
potential_trunks = {_id: uint32, trunk: TrunkBlock}
potential_blocks = {_id: uint32, block: FullBlock}
## NOT USED potential_blocks_received = {_id: uint32, event: Object}
candidate_blocks = {_id: bytes32, body: BlockBody, 
                    header: BlockHeaderData, pos: ProofOfSpace}
unfinished_blocks = {_id: bytes32, iters: uint64, block: FullBlock}
unfinished_blocks_leader = {_id: bytes32, iters: uint64}
sync_mode = {_id: 0, value: bool}
        """
        getc = self.db.get_collection
        self.full_blocks = getc("full_blocks")
        self.potential_heads = getc("potential_heads")
        self.potential_heads_full_blocks = getc("potential_heads_full_blocks")
        self.potential_trunks = getc("potential_trunks")
        self.potential_blocks = getc("potential_blocks")
        self.candidate_blocks = getc("candidate_blocks")
        self.unfinished_blocks = getc("unfinished_blocks")
        self.unfinished_blocks_leader = getc("unfinished_blocks_leader")
        self.sync_mode = getc("sync_mode")

        # asyncio.get_event_loop().run_until_complete(self._set_default_sync_mode(True))

        return None

    async def save_block(self, block: FullBlock) -> None:
        header_hash = block.header_hash()
        await self.full_blocks.find_one_and_update(
            {"_id": header_hash}, {"_id": header_hash, "block": block}, upsert=True
        )

    async def get_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        query = await self.full_blocks.find_one(header_hash)
        if query is not None:
            return query.block

    async def set_sync_mode(self, sync_mode):
        await self.full_blocks.update_one(
            {"_id": 0}, {"$set": {"_id": 0, "value": sync_mode}}, upsert=True
        )

    async def get_sync_mode(self) -> bool:
        query = await self.sync_mode.find_one(header_hash)
        return query.value

    async def _set_default_sync_mode(self, sync_mode):
        query = await self.sync_mode.find_one({"_id": 0})
        if query is None:
            await self.set_sync_mode(sync_mode)

    async def clear_sync_info(self):
        await self.db.drop_collection(self.potential_heads)
        await self.db.drop_collection(self.potential_heads_full_blocks)
        await self.db.drop_collection(self.potential_trunks)
        await self.db.drop_collection(self.potential_blocks)

    async def add_potential_head(self, header_hash: bytes32) -> None:
        await self.potential_heads.find_one_and_update(
            {"_id": header_hash}, {"$inc": {"value": 1}}, upsert=True
        )

    async def get_potential_heads_from_hash(self, header_hash: bytes32) -> int:
        query = await self.potential_heads.find_one({"_id": header_hash})
        return query.value if query else None

    # async def add_potential_heads_full_block
    # async def get_potential_heads_full_block

    async def add_potential_trunk(self, block: TrunkBlock) -> None:
        await self.potential_trunks.find_one_and_update(
            {"_id": block.height},
            {"$set": {"_id": block.height, "block": block}},
            upsert=True,
        )

    async def get_potential_trunk(self, height: uint32) -> Optional[TrunkBlock]:
        query = await self.potential_trunks.find_one({"_id": height})
        return query.value if query else None

    async def add_potential_block(self, block: FullBlock) -> None:
        await self.potential_blocks.find_one_and_update(
            {"_id": block.height},
            {"$set": {"_id": block.height, "block": block}},
            upsert=True,
        )

    async def get_potential_block(self, height: uint32) -> Optional[FullBlock]:
        query = await self.potential_blocks.find_one({"_id": height})
        return query["block"] if query else None

    # async def set_potential_blocks_received
    # async def get_potential_blocks_received

    async def add_candidate_block(
        self,
        pos_hash: bytes32,
        body: BlockBody,
        header: BlockHeaderData,
        pos: ProofOfSpace,
    ):
        await self.candidate_blocks.find_one_and_update(
            {"_id": pos_hash},
            {"$set": {"_id": pos_hash, "body": body, "header": header, "pos": pos}},
            upsert=True,
        )

    async def get_candidate_block(
        self, pos_hash: bytes32
    ) -> Optional[Tuple[BlockBody, BlockHeaderData, ProofOfSpace]]:
        query = await self.candidate_blocks.find_one({"_id": pos_hash})
        return (query.body, query.header, query.pos) if query else None


"""  # TODO: remove when tested better
if 0:
    async def DEBUG():
        print("started")
        db = FullNodeDatabase("test3")
        from src.consensus.constants import constants

        genesis = FullBlock.from_bytes(constants["GENESIS_BLOCK"])
        await db.add_potential_block(genesis)
        ans = await db.get_potential_block(0)
        print("got block", ans)
        print("heh")
    Database.loop.run_until_complete(DEBUG())
"""
