from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from chia_rs import BlockRecord, FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.blockchain_interface import BlockRecordsProtocol, BlocksProtocol, MMRManagerProtocol
from chia.util.errors import Err


class AugmentedBlockchainValidationError(AssertionError):
    pass


class _ReadOnlyMMRManager:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[MMRManagerProtocol] = cast("_ReadOnlyMMRManager", None)

    _wrapped: MMRManagerProtocol

    def __init__(self, wrapped: MMRManagerProtocol) -> None:
        self._wrapped = wrapped

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32,
        new_sp_index: int,
        starts_new_slot: bool,
        blocks: BlockRecordsProtocol,
        fork_height: uint32 | None = None,
    ) -> bytes32 | None:
        return self._wrapped.get_mmr_root_for_block(
            prev_header_hash, new_sp_index, starts_new_slot, blocks, fork_height
        )

    def get_current_mmr_root(self) -> bytes32 | None:
        return self._wrapped.get_current_mmr_root()

    def add_block_to_mmr(self, header_hash: bytes32, prev_hash: bytes32, height: uint32) -> None:
        raise RuntimeError("read-only MMR manager does not allow mutation")

    def rollback_to_height(self, target_height: int, blocks: BlockRecordsProtocol) -> None:
        raise RuntimeError("read-only MMR manager does not allow mutation")

    def get_aggrtegate_from(self) -> uint32:
        return self._wrapped.get_aggrtegate_from()

    def copy(self) -> MMRManagerProtocol:
        return _ReadOnlyMMRManager(self._wrapped)


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
    _overlay_floor: tuple[uint32, bytes32] | None
    mmr_manager: MMRManagerProtocol

    def __init__(self, underlying: BlocksProtocol) -> None:
        self._underlying = underlying
        self._extra_blocks = {}
        self._height_to_hash = {}
        self._overlay_floor = None
        self.mmr_manager = underlying.mmr_manager.copy()

    def _get_block_record(self, header_hash: bytes32) -> BlockRecord | None:
        eb = self._extra_blocks.get(header_hash)
        if eb is None:
            return None
        return eb[1]

    def _recompute_overlay_floor_from_map(self) -> None:
        if not self._height_to_hash:
            self._overlay_floor = None
            return

        min_overlay_height = min(self._height_to_hash)
        self._overlay_floor = (min_overlay_height, self._height_to_hash[min_overlay_height])

    def _update_overlay_floor_on_insert(self, height: uint32, header_hash: bytes32) -> None:
        floor = self._overlay_floor
        if floor is None or height <= floor[0]:
            self._overlay_floor = (height, header_hash)

    def _min_overlay_entry(self) -> tuple[uint32, bytes32] | None:
        """
        Return the cached minimum overlay height/hash pair.
        """
        return self._overlay_floor

    def _get_fork_height(self) -> uint32 | None:
        """
        Find the fork point by walking backward from the lowest overlay block
        until we find a hash matching the underlying chain's height_to_hash.
        """
        min_overlay = self._min_overlay_entry()
        if min_overlay is None:
            return None

        _, overlay_hash = min_overlay
        br = self.try_block_record(overlay_hash)
        assert br is not None

        while br.height > 0:
            prev_height = uint32(br.height - 1)
            if self._underlying.height_to_hash(prev_height) == br.prev_hash:
                return prev_height

            # All fork ancestors should be in cache (recently validated orphans)
            br = self._underlying.try_block_record(br.prev_hash)
            assert br is not None

        # No common ancestor — genesis-level fork or batch starting from genesis
        return None

    def _overlay_hash_from_closest_height(self, height: uint32) -> bytes32 | None:
        """
        Resolve a hash for ``height`` by walking backward from the minimum
        overlay height.

        This fills gaps where intermediate fork blocks are present as orphan
        block records but not explicitly materialized in ``_height_to_hash``.
        """
        if not self._extra_blocks:
            return None

        min_overlay = self._min_overlay_entry()
        if min_overlay is None:
            return None

        min_overlay_height, current_hash = min_overlay
        if height >= min_overlay_height:
            return None

        current = self.try_block_record(current_hash)
        assert current is not None

        while current.height > height:
            parent = self._underlying.try_block_record(current.prev_hash)
            assert parent is not None
            current = parent

        assert current.height == height
        return current.header_hash

    def copy_for_reader(self) -> AugmentedBlockchain:
        """
        Create an immutable-by-convention snapshot for worker-thread reads.

        The returned instance shares the underlying blockchain reference, owns
        independent overlay maps, and uses a shared read-only MMR manager view.
        """
        snapshot = AugmentedBlockchain(self._underlying)
        snapshot._extra_blocks = self._extra_blocks.copy()
        snapshot._height_to_hash = self._height_to_hash.copy()
        snapshot._overlay_floor = self._overlay_floor
        snapshot.mmr_manager = _ReadOnlyMMRManager(self.mmr_manager)
        return snapshot

    def add_extra_block(self, block: FullBlock, block_record: BlockRecord) -> None:
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
        self._update_overlay_floor_on_insert(block_record.height, block_record.header_hash)

    def remove_extra_block(self, hh: bytes32) -> None:
        if hh not in self._extra_blocks:
            return

        block_record = self._extra_blocks.pop(hh)[1]
        floor = self._overlay_floor
        floor_height = None if floor is None else floor[0]
        removed_floor = False
        if self._underlying.contains_block(block_record.header_hash, block_record.height):
            height_to_remove = block_record.height
            for h in range(height_to_remove, -1, -1):
                h_uint32 = uint32(h)
                if h_uint32 not in self._height_to_hash:
                    break
                del self._height_to_hash[h_uint32]
                if floor_height is not None and h_uint32 == floor_height:
                    removed_floor = True

        if removed_floor:
            self._recompute_overlay_floor_from_map()

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
        self._underlying.add_block_record(block_record)
        self._height_to_hash[block_record.height] = block_record.header_hash
        self._update_overlay_floor_on_insert(block_record.height, block_record.header_hash)
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
        header_hash = self._height_to_hash.get(height)
        if header_hash is not None:
            ret = self._get_block_record(header_hash)
            if ret is not None:
                return ret
            return self._underlying.block_record(header_hash)
        return self._underlying.height_to_block_record(height)

    def height_to_hash(self, height: uint32) -> bytes32 | None:
        ret = self._height_to_hash.get(height)
        if ret is not None:
            return ret

        ret = self._overlay_hash_from_closest_height(height)
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

    def get_mmr_root_for_block(
        self,
        prev_header_hash: bytes32,
        new_sp_index: int,
        starts_new_slot: bool,
    ) -> bytes32 | None:
        return self.mmr_manager.get_mmr_root_for_block(
            prev_header_hash, new_sp_index, starts_new_slot, self, fork_height=self._get_fork_height()
        )

    def get_current_mmr_root(self) -> bytes32 | None:
        return self.mmr_manager.get_current_mmr_root()
