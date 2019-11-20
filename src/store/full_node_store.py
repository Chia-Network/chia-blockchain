from typing import Tuple, Optional, Dict, Counter, List
import collections
from asyncio import Lock, Event
from src.types.proof_of_space import ProofOfSpace
from src.types.header import HeaderData
from src.types.header_block import HeaderBlock
from src.types.body import Body
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64


class FullNodeStore:
    def __init__(self):
        self.lock = Lock()

    async def initialize(self):
        self.full_blocks: Dict[bytes32, FullBlock] = {}

        self.sync_mode: bool = True
        # Block headers and blocks which we think might be heads, but we haven't verified yet.
        # All these are used during sync mode
        self.potential_heads: Counter[bytes32] = collections.Counter()
        self.potential_heads_full_blocks: Dict[bytes32, FullBlock] = collections.Counter()
        # Headers/headers downloaded for the during sync, by height
        self.potential_headers: Dict[uint32, HeaderBlock] = {}
        # Blocks downloaded during sync, by height
        self.potential_blocks: Dict[uint32, FullBlock] = {}
        # Event, which gets set whenever we receive the block at each height. Waited for by sync().
        self.potential_blocks_received: Dict[uint32, Event] = {}

        self.potential_future_blocks: List[FullBlock] = []

        # These are the blocks that we created, but don't have the PoS from farmer yet,
        # keyed from the proof of space hash
        self.candidate_blocks: Dict[bytes32, Tuple[Body, HeaderData, ProofOfSpace]] = {}

        # These are the blocks that we created, have PoS, but not PoT yet, keyed from the
        # challenge hash and iterations
        self.unfinished_blocks: Dict[Tuple[bytes32, uint64], FullBlock] = {}
        # Latest height with unfinished blocks, and expected timestamp of the finishing
        self.unfinished_blocks_leader: Tuple[uint32, uint64] = (uint32(0), uint64(9999999999))

        self.proof_of_time_estimate_ips: uint64 = uint64(3000)

    async def get_lock(self) -> Lock:
        return self.lock

    async def save_block(self, block: FullBlock):
        self.full_blocks[block.header_hash] = block

    async def get_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.full_blocks.get(header_hash)

    async def set_sync_mode(self, sync_mode: bool):
        self.sync_mode = sync_mode

    async def get_sync_mode(self) -> bool:
        return self.sync_mode

    async def clear_sync_information(self):
        self.potential_heads.clear()
        self.potential_heads_full_blocks.clear()
        self.potential_headers.clear()
        self.potential_blocks.clear()
        self.potential_blocks_received.clear()
        self.potential_future_blocks.clear()

    async def add_potential_head(self, header_hash: bytes32):
        self.potential_heads[header_hash] += 1

    async def get_potential_heads(self) -> Dict[bytes32, int]:
        return self.potential_heads

    async def add_potential_heads_full_block(self, block: FullBlock):
        self.potential_heads_full_blocks[block.header_hash] = block

    async def get_potential_heads_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.potential_heads_full_blocks.get(header_hash)

    async def add_potential_header(self, block: HeaderBlock):
        self.potential_headers[block.height] = block

    async def get_potential_header(self, height: uint32) -> Optional[HeaderBlock]:
        return self.potential_headers.get(height)

    async def add_potential_block(self, block: FullBlock):
        self.potential_blocks[block.height] = block

    async def get_potential_block(self, height: uint32) -> Optional[FullBlock]:
        return self.potential_blocks.get(height)

    async def set_potential_blocks_received(self, height: uint32, event: Event):
        self.potential_blocks_received[height] = event

    async def get_potential_blocks_received(self, height: uint32) -> Event:
        return self.potential_blocks_received[height]

    async def add_potential_future_block(self, block: FullBlock):
        self.potential_future_blocks.append(block)

    async def get_potential_future_blocks(self):
        return self.potential_future_blocks

    async def add_candidate_block(self, pos_hash: bytes32, block: Tuple[Body, HeaderData, ProofOfSpace]):
        self.candidate_blocks[pos_hash] = block

    async def get_candidate_block(self, pos_hash: bytes32) -> Optional[Tuple[Body, HeaderData, ProofOfSpace]]:
        return self.candidate_blocks.get(pos_hash)

    async def add_unfinished_block(self, key: Tuple[bytes32, uint64], block: FullBlock):
        self.unfinished_blocks[key] = block

    async def get_unfinished_block(self, key=Tuple[bytes32, uint64]) -> Optional[FullBlock]:
        return self.unfinished_blocks.get(key)

    async def get_unfinished_blocks(self) -> Dict[Tuple[bytes32, uint64], FullBlock]:
        return self.unfinished_blocks

    async def set_unfinished_block_leader(self, value: Tuple[uint32, uint64]):
        self.unfinished_blocks_leader = value

    async def get_unfinished_block_leader(self) -> Tuple[uint32, uint64]:
        return self.unfinished_blocks_leader

    async def set_proof_of_time_estimate_ips(self, estimate: uint64):
        self.proof_of_time_estimate_ips = estimate

    async def get_proof_of_time_estimate_ips(self) -> uint64:
        return self.proof_of_time_estimate_ips
