from typing import Dict, List, Optional

from src.consensus.blockchain import Blockchain
from src.consensus.sub_block_record import SubBlockRecord
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
        header_blocks: Dict[uint32, HeaderBlock],
        maxheight: uint32,
        sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {},
    ):
        self._sub_blocks = sub_blocks
        self._header_cache = header_blocks
        self._sub_height_to_hash = sub_height_to_hash
        self._sub_epoch_summaries = sub_epoch_summaries
        self._maxheight = maxheight

    def header_block(self, header_hash: bytes32) -> Optional[HeaderBlock]:
        if header_hash not in self._header_cache:
            return None

        return self._header_cache[header_hash]

    def height_to_header_block(self, height: uint32) -> Optional[HeaderBlock]:
        header_hash = self._height_to_hash(height)
        if header_hash is None:
            return None
        return self._header_cache[header_hash]

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


async def init_block_cache(blockchain: Blockchain, start: uint32 = uint32(0), stop: uint32 = uint32(0)) -> BlockCache:
    full_blocks: List[FullBlock] = []
    batch_blocks: List[uint32] = []

    if stop == 0 and blockchain.peak_height is not None:
        stop = blockchain.peak_height

    for x in range(start, stop + 1):
        batch_blocks.append(uint32(x))

        if len(batch_blocks) == BlockCache.BATCH_SIZE:
            blocks = await blockchain.block_store.get_full_blocks_at(batch_blocks)
            full_blocks.extend(blocks)
            batch_blocks = []

    if len(batch_blocks) != 0:
        blocks = await blockchain.block_store.get_full_blocks_at(batch_blocks)
        full_blocks.extend(blocks)
        batch_blocks = []

    # fetch remaining blocks
    blocks = await blockchain.block_store.get_full_blocks_at(batch_blocks)
    full_blocks.extend(blocks)

    # convert to FullBlocks HeaderBlocks
    header_blocks: Dict[bytes32, HeaderBlock] = {}
    for block in full_blocks:
        header_blocks[block.header_hash] = await block.get_block_header()

    return BlockCache(
        blockchain.sub_blocks, blockchain.sub_height_to_hash, header_blocks, stop, blockchain.sub_epoch_summaries
    )


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
        blockchain.sub_blocks, blockchain.sub_height_to_hash, header_block_map, stop, blockchain.sub_epoch_summaries
    )
