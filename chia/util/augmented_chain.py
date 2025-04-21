from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional, cast

from chia_rs import BlockRecord, FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_interface import BlocksProtocol
from chia.util.errors import Err


class AugmentedBlockchain:
    """
    This class wraps a BlocksProtocol and forwards calls to it, when
    looking up block records. It allows an in-memory cache of block records to
    fall back onto in case a block is not available in the underlying
    BlocksProtocol.
    This is especially useful when validating blocks in parallel. The batch of
    blocks will not have been added to the underlying blockchain until they've
    all been validated, but the validation requires them to be available as-if
    they were valid.
    """

    if TYPE_CHECKING:
        _protocol_check: ClassVar[BlocksProtocol] = cast("AugmentedBlockchain", None)

    _underlying: BlocksProtocol
    _extra_blocks: dict[bytes32, tuple[FullBlock, BlockRecord]]
    _height_to_hash: dict[uint32, bytes32]

    def __init__(self, underlying: BlocksProtocol) -> None:
        self._underlying = underlying
        self._extra_blocks = {}
        self._height_to_hash = {}

    def _get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        eb = self._extra_blocks.get(header_hash)
        if eb is None:
            return None
        return eb[1]

    def add_extra_block(self, block: FullBlock, block_record: BlockRecord) -> None:
        assert block.header_hash == block_record.header_hash
        self._extra_blocks[block_record.header_hash] = (block, block_record)
        self._height_to_hash[block_record.height] = block_record.header_hash

    def remove_extra_block(self, hh: bytes32) -> None:
        if hh not in self._extra_blocks:
            return

        block_record = self._extra_blocks.pop(hh)[1]
        if self._underlying.contains_block(block_record.header_hash, block_record.height):
            height_to_remove = block_record.height
            for h in range(height_to_remove, -1, -1):
                if h not in self._height_to_hash:
                    break
                del self._height_to_hash[uint32(h)]

    # BlocksProtocol
    async def lookup_block_generators(self, header_hash: bytes32, generator_refs: set[uint32]) -> dict[uint32, bytes]:
        generators: dict[uint32, bytes] = {}

        # traverse the additional blocks (if any) and resolve heights into
        # generators
        to_remove = []
        curr: Optional[tuple[FullBlock, BlockRecord]] = self._extra_blocks.get(header_hash)
        while curr is not None:
            b = curr[0]
            if b.height in generator_refs:
                if b.transactions_generator is None:
                    raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
                generators[b.height] = bytes(b.transactions_generator)
                to_remove.append(b.height)
            header_hash = b.prev_header_hash
            curr = self._extra_blocks.get(header_hash)
        for i in to_remove:
            generator_refs.remove(i)

        if len(generator_refs) > 0:
            generators.update(await self._underlying.lookup_block_generators(header_hash, generator_refs))
        return generators

    async def get_block_record_from_db(self, header_hash: bytes32) -> Optional[BlockRecord]:
        ret = self._get_block_record(header_hash)
        if ret is not None:
            return ret
        return await self._underlying.get_block_record_from_db(header_hash)

    def add_block_record(self, block_record: BlockRecord) -> None:
        self._underlying.add_block_record(block_record)
        self._height_to_hash[block_record.height] = block_record.header_hash
        # now that we're adding the block to the underlying blockchain, we don't
        # need to keep the extra block around anymore
        hh = block_record.header_hash
        if hh in self._extra_blocks:
            del self._extra_blocks[hh]

    # BlockRecordsProtocol
    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        ret = self._get_block_record(header_hash)
        if ret is not None:
            return ret
        return self._underlying.try_block_record(header_hash)

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        ret = self._get_block_record(header_hash)
        if ret is not None:
            return ret
        return self._underlying.block_record(header_hash)

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        header_hash = self._height_to_hash.get(height)
        if header_hash is not None:
            ret = self._get_block_record(header_hash)
            if ret is not None:
                return ret
            return self._underlying.block_record(header_hash)
        return self._underlying.height_to_block_record(height)

    def height_to_hash(self, height: uint32) -> Optional[bytes32]:
        ret = self._height_to_hash.get(height)
        if ret is not None:
            return ret
        return self._underlying.height_to_hash(height)

    def contains_block(self, header_hash: bytes32, height: uint32) -> bool:
        block_hash_from_hh = self.height_to_hash(height)
        if block_hash_from_hh is None or block_hash_from_hh != header_hash:
            return False
        return True

    def contains_height(self, height: uint32) -> bool:
        return (height in self._height_to_hash) or self._underlying.contains_height(height)

    async def prev_block_hash(self, header_hashes: list[bytes32]) -> list[bytes32]:
        ret: list[bytes32] = []
        for hh in header_hashes:
            b = self._extra_blocks.get(hh)
            if b is not None:
                ret.append(b[1].prev_hash)
            else:
                ret.extend(await self._underlying.prev_block_hash([hh]))
        return ret
