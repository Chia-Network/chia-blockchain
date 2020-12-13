from typing import Dict, List

from src.consensus.blockchain import Blockchain
from src.consensus.sub_block_record import SubBlockRecord
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint32
from src.wallet.wallet_blockchain import WalletBlockchain


class BlockCache:
    def __init__(
        self,
        sub_blocks: Dict[bytes32, SubBlockRecord],
        sub_height_to_hash: Dict[uint32, bytes32],
        header_blocks: Dict[uint32, HeaderBlock],
    ):
        self._sub_blocks = sub_blocks
        self._header_cache = header_blocks
        self._sub_height_to_hash = sub_height_to_hash

    def header_block(self, header_hash: bytes32) -> HeaderBlock:
        return self._header_cache[header_hash]

    def height_to_header_block(self, height: uint32) -> HeaderBlock:
        return self._header_cache[self._height_to_hash(height)]

    def sub_block_record(self, header_hash: bytes32) -> SubBlockRecord:
        return self._sub_blocks[header_hash]

    def height_to_sub_block_record(self, height: uint32) -> SubBlockRecord:
        return self._sub_blocks[self._height_to_hash(height)]

    def max_height(self) -> uint32:
        return uint32(len(self._sub_blocks) - 1)

    def _height_to_hash(self, height: uint32) -> bytes32:
        return self._sub_height_to_hash[height]


async def init_block_cache(blockchain: Blockchain, start: int = 0, stop: int = 0) -> BlockCache:
    batch_size = 200
    full_blocks: List[FullBlock] = []
    batch_blocks: List[uint32] = []

    if stop == 0 and blockchain.peak_height is not None:
        stop = blockchain.peak_height

    for x in range(start, stop):
        batch_blocks.append(uint32(x))

        if len(batch_blocks) == batch_size:
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

    return BlockCache(blockchain.sub_blocks, blockchain.sub_height_to_hash, header_blocks)


async def init_wallet_block_cache(blockchain: WalletBlockchain, start: int = 0, stop: int = 0) -> BlockCache:
    batch_size = 200
    header_blocks: List[HeaderBlock] = []
    batch_blocks: List[uint32] = []

    if stop == 0 and blockchain.peak_height is not None:
        stop = blockchain.peak_height

    for x in range(start, stop):
        batch_blocks.append(uint32(x))

        if len(batch_blocks) == batch_size:
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

    return BlockCache(blockchain.sub_blocks, blockchain.sub_height_to_hash, header_block_map)
