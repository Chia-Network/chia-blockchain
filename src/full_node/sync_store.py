import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32

log = logging.getLogger(__name__)


class SyncStore:
    # Whether or not we are syncing
    sync_mode: bool
    # Whether we are waiting for tips (at the start of sync) or already syncing
    waiting_for_tips: bool
    # Potential new tips that we have received from others.
    potential_tips: Dict[bytes32, FullBlock]
    # List of all header hashes up to the tip, download up front
    potential_hashes: List[bytes32]
    # Blocks received from other peers during sync
    potential_blocks: Dict[uint32, FullBlock]
    # Event to signal when header hashes are received
    potential_hashes_received: Optional[asyncio.Event]
    # Event to signal when blocks are received at each height
    potential_blocks_received: Dict[uint32, asyncio.Event]
    # Blocks that we have finalized during sync, queue them up for adding after sync is done
    potential_future_blocks: List[FullBlock]

    @classmethod
    async def create(cls):
        self = cls()

        self.sync_mode = False
        self.waiting_for_tips = True
        self.potential_tips = {}
        self.potential_hashes = []
        self.potential_blocks = {}
        self.potential_hashes_received = None
        self.potential_blocks_received = {}
        self.potential_future_blocks = []
        return self

    def set_sync_mode(self, sync_mode: bool) -> None:
        self.sync_mode = sync_mode

    def get_sync_mode(self) -> bool:
        return self.sync_mode

    def set_waiting_for_tips(self, waiting_for_tips: bool) -> None:
        self.waiting_for_tips = waiting_for_tips

    def get_waiting_for_tips(self) -> bool:
        return self.waiting_for_tips

    async def clear_sync_info(self):
        self.potential_tips.clear()
        self.potential_blocks.clear()
        self.potential_blocks_received.clear()
        self.potential_future_blocks.clear()
        self.waiting_for_tips = True

    def get_potential_tips_tuples(self) -> List[Tuple[bytes32, FullBlock]]:
        return list(self.potential_tips.items())

    def add_potential_tip(self, block: FullBlock) -> None:
        self.potential_tips[block.header_hash] = block

    def get_potential_tip(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.potential_tips.get(header_hash, None)

    def set_potential_hashes(self, potential_hashes: List[bytes32]) -> None:
        self.potential_hashes = potential_hashes

    def get_potential_hashes(self) -> List[bytes32]:
        return self.potential_hashes

    def set_potential_hashes_received(self, event: asyncio.Event):
        self.potential_hashes_received = event

    def get_potential_hashes_received(self) -> Optional[asyncio.Event]:
        return self.potential_hashes_received

    def add_potential_future_block(self, block: FullBlock):
        self.potential_future_blocks.append(block)

    def get_potential_future_blocks(self):
        return self.potential_future_blocks
