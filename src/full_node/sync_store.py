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
    # Whether we are waiting for peaks (at the start of sync) or already syncing
    waiting_for_peaks: bool
    # Potential new peaks that we have received from others.
    potential_peaks: Dict[bytes32, FullBlock]
    # Blocks received from other peers during sync
    potential_blocks: Dict[uint32, FullBlock]
    # Event to signal when blocks are received at each height
    potential_blocks_received: Dict[uint32, asyncio.Event]
    # Blocks that we have finalized during sync, queue them up for adding after sync is done
    potential_future_blocks: List[FullBlock]
    # A map from sub height to header hash of sub-blocks added to the chain
    header_hashes_added: Dict[uint32, bytes32]

    @classmethod
    async def create(cls):
        self = cls()

        self.sync_mode = False
        self.waiting_for_peaks = True
        self.potential_peaks = {}
        self.potential_blocks = {}
        self.potential_blocks_received = {}
        self.potential_future_blocks = []
        self.header_hashes_added = {}
        return self

    def set_sync_mode(self, sync_mode: bool) -> None:
        self.sync_mode = sync_mode

    def get_sync_mode(self) -> bool:
        return self.sync_mode

    async def clear_sync_info(self):
        self.potential_peaks.clear()
        self.potential_blocks.clear()
        self.potential_blocks_received.clear()
        self.potential_future_blocks.clear()
        self.header_hashes_added.clear()
        self.waiting_for_peaks = True

    def get_potential_peaks_tuples(self) -> List[Tuple[bytes32, FullBlock]]:
        return list(self.potential_peaks.items())

    def add_potential_peak(self, block: FullBlock) -> None:
        self.potential_peaks[block.header_hash] = block

    def get_potential_peak(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.potential_peaks.get(header_hash, None)

    def add_potential_future_block(self, block: FullBlock):
        self.potential_future_blocks.append(block)

    def get_potential_future_blocks(self):
        return self.potential_future_blocks

    def add_header_hashes_added(self, height: uint32, header_hash: bytes32):
        self.header_hashes_added[height] = header_hash

    def get_header_hashes_added(self, height: uint32) -> Optional[bytes32]:
        return self.header_hashes_added.get(height, None)
