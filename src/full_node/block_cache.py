import logging
from typing import Dict, List, Optional

from src.consensus.blockchain import Blockchain
from src.consensus.sub_block_record import SubBlockRecord
from src.full_node.block_store import BlockStore
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.util.ints import uint32
from src.wallet.wallet_blockchain import WalletBlockchain


class BlockCache:
    BATCH_SIZE = 300

    def __init__(
        self,
        sub_blocks: Dict[bytes32, SubBlockRecord],
        sub_height_to_hash: Dict[uint32, bytes32],
        maxheight: uint32,
        header_blocks: Dict[uint32, HeaderBlock] = {},
        sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {},
        block_store: Optional[BlockStore] = None,
    ):
        self._sub_blocks = sub_blocks
        self._header_cache = header_blocks
        self._sub_height_to_hash = sub_height_to_hash
        self._sub_epoch_summaries = sub_epoch_summaries
        self._maxheight = maxheight
        self.block_store = block_store
        self.log = logging.getLogger(__name__)

    async def header_block(self, header_hash: bytes32) -> Optional[HeaderBlock]:
        if header_hash not in self._header_cache:
            if self.block_store is not None:
                block = await self.block_store.get_full_block(header_hash)
                if block is not None:
                    self.log.debug(f"cache miss {block.sub_block_height} {block.header_hash}")
                    return await block.get_block_header()
            return None

        return self._header_cache[header_hash]

    async def height_to_header_block(self, height: uint32) -> Optional[HeaderBlock]:
        header_hash = self._height_to_hash(height)
        if header_hash is None:
            return None
        return await self.header_block(header_hash)

    def sub_block_record(self, header_hash: bytes32) -> Optional[SubBlockRecord]:
        if header_hash not in self._sub_blocks:
            return None

        return self._sub_blocks[header_hash]

    def height_to_sub_block_record(self, height: uint32) -> Optional[SubBlockRecord]:
        header_hash = self._height_to_hash(height)
        if header_hash is None:
            return None
        return self.sub_block_record(header_hash)

    def max_height(self) -> uint32:
        return self._maxheight

    def get_ses_heights(self) -> List[bytes32]:
        return sorted(self._sub_epoch_summaries.keys())

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self._sub_epoch_summaries[height]

    def _height_to_hash(self, height: uint32) -> Optional[bytes32]:
        if height not in self._sub_height_to_hash:
            return None
        return self._sub_height_to_hash[height]

    def clean(self):
        self._header_cache = {}

    async def init_headers(self, start: uint32, stop: uint32):
        if self.block_store is None:
            return
        self._header_cache = {}
        self.log.debug(f"init headers {start} {stop}")
        self._header_cache = await init_header_cache(self.block_store, start, stop)
        self._maxheight = stop


async def init_block_cache(blockchain: Blockchain, start: uint32 = uint32(0), stop: uint32 = uint32(0)) -> BlockCache:
    header_blocks = await init_header_cache(blockchain.block_store, start, stop)
    if stop == 0 and blockchain.peak_height is not None:
        stop = blockchain.peak_height
    return BlockCache(
        blockchain.sub_blocks,
        blockchain.sub_height_to_hash,
        stop,
        header_blocks,
        blockchain.sub_epoch_summaries,
        blockchain.block_store,
    )


async def init_header_cache(block_store: BlockStore, start: uint32, stop: uint32) -> Dict[bytes32, HeaderBlock]:
    full_blocks: List[FullBlock] = []
    batch_blocks: List[uint32] = []
    for x in range(start, stop + 1):
        batch_blocks.append(uint32(x))

        if len(batch_blocks) == BlockCache.BATCH_SIZE:
            blocks = await block_store.get_full_blocks_at(batch_blocks)
            full_blocks.extend(blocks)
            batch_blocks = []

    if len(batch_blocks) != 0:
        blocks = await block_store.get_full_blocks_at(batch_blocks)
        full_blocks.extend(blocks)
        batch_blocks = []

    # fetch remaining blocks
    blocks = await block_store.get_full_blocks_at(batch_blocks)
    full_blocks.extend(blocks)

    # convert to FullBlocks HeaderBlocks
    header_blocks: Dict[bytes32, HeaderBlock] = {}
    for block in full_blocks:
        header_blocks[block.header_hash] = await block.get_block_header()
    return header_blocks


async def init_wallet_block_cache(
    blockchain: WalletBlockchain, start: uint32 = uint32(0), stop: uint32 = uint32(0)
) -> BlockCache:
    header_blocks: List[HeaderBlock] = []
    batch_blocks: List[uint32] = []

    if stop == 0 and blockchain.peak_height is not None:
        stop = blockchain.peak_height

    for x in range(start, stop):
        batch_blocks.append(uint32(x))

        if len(batch_blocks) == BlockCache.BATCH_SIZE:
            blocks = await blockchain.block_store.get_header_block_at(batch_blocks)
            header_blocks.extend(blocks)
            batch_blocks = []

    # fetch remaining blocks
    blocks = await blockchain.block_store.get_header_block_at(batch_blocks)
    header_blocks.extend(blocks)

    # map
    header_block_map: Dict[bytes32, HeaderBlock] = {}
    for block in header_blocks:
        header_block_map[block.header_hash] = block

    return BlockCache(
        blockchain.sub_blocks, blockchain.sub_height_to_hash, stop, header_block_map, blockchain.sub_epoch_summaries
    )
