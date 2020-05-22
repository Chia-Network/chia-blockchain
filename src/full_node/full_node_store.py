import logging
import aiosqlite
from typing import Dict, List, Optional, Tuple

from src.types.program import Program
from src.types.full_block import FullBlock
from src.types.header import HeaderData
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64

log = logging.getLogger(__name__)


class FullNodeStore:
    db: aiosqlite.Connection
    # Current estimate of the speed of the network timelords
    proof_of_time_estimate_ips: uint64
    # Proof of time heights
    proof_of_time_heights: Dict[Tuple[bytes32, uint64], uint32]
    # Our best unfinished block
    unfinished_blocks_leader: Tuple[uint32, uint64]
    # Blocks which we have created, but don't have proof of space yet, old ones are cleared
    candidate_blocks: Dict[
        bytes32,
        Tuple[Optional[Program], Optional[bytes], HeaderData, ProofOfSpace, uint32],
    ]
    # Header hashes of unfinished blocks that we have seen recently
    seen_unfinished_blocks: set
    # Blocks which we have received but our blockchain does not reach, old ones are cleared
    disconnected_blocks: Dict[bytes32, FullBlock]

    @classmethod
    async def create(cls, connection):
        self = cls()

        self.db = connection

        await self.db.commit()

        self.proof_of_time_estimate_ips = uint64(10000)
        self.proof_of_time_heights = {}
        self.unfinished_blocks_leader = (
            uint32(0),
            uint64((1 << 64) - 1),
        )
        self.candidate_blocks = {}
        self.seen_unfinished_blocks = set()
        self.disconnected_blocks = {}

        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS unfinished_blocks("
            "challenge_hash text,"
            "iterations bigint,"
            "block blob,"
            "height int,"
            "PRIMARY KEY (challenge_hash, iterations))"
        )
        await self.db.commit()
        return self

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

    def add_candidate_block(
        self,
        pos_hash: bytes32,
        transactions_generator: Optional[Program],
        transactions_filter: Optional[bytes],
        header: HeaderData,
        pos: ProofOfSpace,
        height: uint32 = uint32(0),
    ):
        self.candidate_blocks[pos_hash] = (
            transactions_generator,
            transactions_filter,
            header,
            pos,
            height,
        )

    def get_candidate_block(
        self, pos_hash: bytes32
    ) -> Optional[Tuple[Optional[Program], Optional[bytes], HeaderData, ProofOfSpace]]:
        res = self.candidate_blocks.get(pos_hash, None)
        if res is None:
            return None
        return (res[0], res[1], res[2], res[3])

    def clear_candidate_blocks_below(self, height: uint32) -> None:
        del_keys = []
        for key, value in self.candidate_blocks.items():
            if value[4] < height:
                del_keys.append(key)
        for key in del_keys:
            try:
                del self.candidate_blocks[key]
            except KeyError:
                pass

    async def add_unfinished_block(
        self, key: Tuple[bytes32, uint64], block: FullBlock
    ) -> None:
        cursor_1 = await self.db.execute(
            "INSERT OR REPLACE INTO unfinished_blocks VALUES(?, ?, ?, ?)",
            (key[0].hex(), key[1], bytes(block), block.height),
        )
        await cursor_1.close()
        await self.db.commit()

    async def get_unfinished_block(
        self, key: Tuple[bytes32, uint64]
    ) -> Optional[FullBlock]:
        cursor = await self.db.execute(
            "SELECT block from unfinished_blocks WHERE challenge_hash=? AND iterations=?",
            (key[0].hex(), key[1]),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return FullBlock.from_bytes(row[0])
        return None

    def seen_unfinished_block(self, header_hash: bytes32) -> bool:
        if header_hash in self.seen_unfinished_blocks:
            return True
        self.seen_unfinished_blocks.add(header_hash)
        return False

    async def clear_seen_unfinished_blocks(self) -> None:
        self.seen_unfinished_blocks.clear()

    async def get_unfinished_blocks(self) -> Dict[Tuple[bytes32, uint64], FullBlock]:
        cursor = await self.db.execute(
            "SELECT challenge_hash, iterations, block from unfinished_blocks"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {(bytes.fromhex(a), b): FullBlock.from_bytes(c) for a, b, c in rows}

    async def clear_unfinished_blocks_below(self, height: uint32) -> None:
        cursor = await self.db.execute(
            "DELETE from unfinished_blocks WHERE height<? ", (height,)
        )
        await cursor.close()
        await self.db.commit()

    def set_unfinished_block_leader(self, key: Tuple[bytes32, uint64]) -> None:
        self.unfinished_blocks_leader = key

    def get_unfinished_block_leader(self) -> Tuple[bytes32, uint64]:
        return self.unfinished_blocks_leader

    def set_proof_of_time_estimate_ips(self, estimate: uint64):
        self.proof_of_time_estimate_ips = estimate

    def get_proof_of_time_estimate_ips(self) -> uint64:
        return self.proof_of_time_estimate_ips

    def add_proof_of_time_heights(
        self, challenge_iters: Tuple[bytes32, uint64], height: uint32
    ) -> None:
        self.proof_of_time_heights[challenge_iters] = height

    def get_proof_of_time_heights(
        self, challenge_iters: Tuple[bytes32, uint64]
    ) -> Optional[uint32]:
        return self.proof_of_time_heights.get(challenge_iters, None)

    def clear_proof_of_time_heights_below(self, height: uint32) -> None:
        del_keys: List = []
        for key, value in self.proof_of_time_heights.items():
            if value < height:
                del_keys.append(key)
        for key in del_keys:
            try:
                del self.proof_of_time_heights[key]
            except KeyError:
                pass
