from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from chia_rs import BlockRecord, FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_interface import BlocksProtocol, MMRManagerProtocol
from chia.util.errors import Err


class AugmentedBlockchainValidationError(AssertionError):
    pass


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
    # The highest height where the augmented chain's block matches the
    # underlying canonical chain.  Heights at or below this delegate to the
    # underlying; heights above it must be resolved from the augmented state.
    _fork_height: uint32 | None
    _read_only: bool
    mmr_manager: MMRManagerProtocol

    def __init__(self, underlying: BlocksProtocol) -> None:
        self._underlying = underlying
        self._extra_blocks = {}
        self._height_to_hash = {}
        self._fork_height = None
        self._read_only = False
        self.mmr_manager = underlying.mmr_manager.copy()

    def _ensure_mutable(self) -> None:
        if self._read_only:
            raise AugmentedBlockchainValidationError("Cannot mutate read-only augmented blockchain snapshot")

    def read_only_snapshot(self) -> AugmentedBlockchain:
        # _underlying is shared by reference; safe because the snapshot is only
        # used for read-only BlockRecordsProtocol calls in a single executor task
        # while the asyncio event loop serializes mutations on the writer side.
        snapshot = AugmentedBlockchain.__new__(AugmentedBlockchain)
        snapshot._underlying = self._underlying
        snapshot._extra_blocks = self._extra_blocks.copy()
        snapshot._height_to_hash = self._height_to_hash.copy()
        snapshot._fork_height = self._fork_height
        snapshot._read_only = True
        snapshot.mmr_manager = self.mmr_manager.copy()
        return snapshot

    def _get_block_record(self, header_hash: bytes32) -> BlockRecord | None:
        eb = self._extra_blocks.get(header_hash)
        if eb is None:
            return None
        return eb[1]

    def _initialize_fork_height(self, block_record: BlockRecord) -> None:
        if self._fork_height is not None:
            return

        # Walk backward from the block's parent to find the fork point: the
        # highest height where the augmented chain's ancestry agrees with the
        # underlying canonical chain.  Blocks between the fork point and the
        # first augmented block may be orphans in the underlying (present in
        # its block record cache but not in its height-to-hash map).
        if block_record.height == 0:
            h = 0
            curr_hash = block_record.header_hash
        else:
            h = int(block_record.height) - 1
            curr_hash = block_record.prev_hash
        while h >= 0:
            canonical = self._underlying.height_to_hash(uint32(h))
            if canonical == curr_hash:
                self._fork_height = uint32(h)
                return
            br = self._underlying.try_block_record(curr_hash)
            if br is None:
                break
            curr_hash = br.prev_hash
            h -= 1
        # No common block found — leave _fork_height as None so
        # height_to_hash resolves entirely from augmented state.

    def add_extra_block(self, block: FullBlock, block_record: BlockRecord) -> None:
        self._ensure_mutable()
        if block.header_hash != block_record.header_hash:
            raise AugmentedBlockchainValidationError(
                f"Block header hash mismatch: block={block.header_hash.hex()[:16]}, "
                f"record={block_record.header_hash.hex()[:16]}"
            )
        if self._height_to_hash:
            max_height = max(self._height_to_hash.keys())
            last_header_hash = self._height_to_hash[max_height]

            if block_record.prev_hash != last_header_hash:
                raise AugmentedBlockchainValidationError(
                    f"New block's prev_hash must match last added block. "
                    f"Expected {last_header_hash.hex()[:16]}, got {block_record.prev_hash.hex()[:16]}"
                )
        elif block_record.height > 0:
            if self._underlying.try_block_record(block_record.prev_hash) is None:
                raise AugmentedBlockchainValidationError(
                    f"First added block's prev_hash must exist in underlying blockchain. "
                    f"Block height {block_record.height}, prev_hash {block_record.prev_hash.hex()[:16]} not found"
                )

        self._extra_blocks[block_record.header_hash] = (block, block_record)
        self._height_to_hash[block_record.height] = block_record.header_hash
        self._initialize_fork_height(block_record)

    def remove_extra_block(self, hh: bytes32) -> None:
        self._ensure_mutable()
        if hh not in self._extra_blocks:
            return

        block_record = self._extra_blocks.pop(hh)[1]
        if self._underlying.contains_block(block_record.header_hash, block_record.height):
            height_to_remove = block_record.height
            for h in range(height_to_remove, -1, -1):
                if h not in self._height_to_hash:
                    break
                del self._height_to_hash[uint32(h)]
            # The cascade only fires once the fork has been promoted to
            # canonical in the underlying, so the fork point advances to
            # the removed block's height.
            self._fork_height = block_record.height

    # BlocksProtocol
    async def lookup_block_generators(self, header_hash: bytes32, generator_refs: set[uint32]) -> dict[uint32, bytes]:
        generators: dict[uint32, bytes] = {}

        # traverse the additional blocks (if any) and resolve heights into
        # generators
        to_remove = []
        curr: tuple[FullBlock, BlockRecord] | None = self._extra_blocks.get(header_hash)
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

    async def get_block_record_from_db(self, header_hash: bytes32) -> BlockRecord | None:
        ret = self._get_block_record(header_hash)
        if ret is not None:
            return ret
        return await self._underlying.get_block_record_from_db(header_hash)

    def add_block_record(self, block_record: BlockRecord) -> None:
        self._ensure_mutable()
        self._underlying.add_block_record(block_record)
        self._height_to_hash[block_record.height] = block_record.header_hash
        self._initialize_fork_height(block_record)
        # now that we're adding the block to the underlying blockchain, we don't
        # need to keep the extra block around anymore
        hh = block_record.header_hash
        if hh in self._extra_blocks:
            del self._extra_blocks[hh]

    # BlockRecordsProtocol
    def try_block_record(self, header_hash: bytes32) -> BlockRecord | None:
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
        header_hash = self.height_to_hash(height)
        if header_hash is None:
            raise ValueError(f"Height is not in blockchain: {height}")
        ret = self._get_block_record(header_hash)
        if ret is not None:
            return ret
        return self._underlying.block_record(header_hash)

    def height_to_hash(self, height: uint32) -> bytes32 | None:
        # At or below the fork point both chains agree — delegate.
        # Also delegate when no augmented blocks exist.
        if not self._height_to_hash or (self._fork_height is not None and height <= self._fork_height):
            return self._underlying.height_to_hash(height)

        # Above the augmented chain's tip — doesn't exist on this fork yet.
        if height > max(self._height_to_hash):
            return None

        # At or above the floor — direct lookup in augmented height map.
        augmented_hash = self._height_to_hash.get(height)
        if augmented_hash is not None:
            return augmented_hash

        # In the gap (fork_height < height < floor): traverse backward from
        # the lowest augmented entry through orphan block records.
        curr_hash = self._height_to_hash[min(self._height_to_hash)]
        br: BlockRecord | None = self.block_record(curr_hash)
        while br is not None and br.height > height:
            curr_hash = br.prev_hash
            br = self.block_record(curr_hash)
        assert br is not None and br.height == height
        return curr_hash

    def contains_block(self, header_hash: bytes32, height: uint32) -> bool:
        block_hash_from_hh = self.height_to_hash(height)
        if block_hash_from_hh is None or block_hash_from_hh != header_hash:
            return False
        return True

    def contains_height(self, height: uint32) -> bool:
        return self.height_to_hash(height) is not None

    async def prev_block_hash(self, header_hashes: list[bytes32]) -> list[bytes32]:
        ret: list[bytes32] = []
        for hh in header_hashes:
            b = self._extra_blocks.get(hh)
            if b is not None:
                ret.append(b[1].prev_hash)
            else:
                ret.extend(await self._underlying.prev_block_hash([hh]))
        return ret

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32,
        new_sp_index: int,
        starts_new_slot: bool,
    ) -> bytes32 | None:
        return self.mmr_manager.get_mmr_root_for_block(
            prev_header_hash, new_sp_index, starts_new_slot, self, fork_height=self._fork_height
        )

    def get_current_mmr_root(self) -> bytes32 | None:
        return self.mmr_manager.get_current_mmr_root()
