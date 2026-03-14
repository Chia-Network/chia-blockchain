from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, cast

import pytest
from chia_rs import BlockRecord, FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia._tests.util.blockchain import create_blockchain
from chia.consensus.augmented_chain import AugmentedBlockchain, AugmentedBlockchainValidationError
from chia.simulator.block_tools import BlockTools
from chia.util.block_cache import BlockCache
from chia.util.errors import Err


@dataclass
class NullBlockchain:
    if TYPE_CHECKING:
        from chia.consensus.blockchain_interface import BlocksProtocol

        _protocol_check: ClassVar[BlocksProtocol] = cast("NullBlockchain", None)

    added_blocks: set[bytes32] = field(default_factory=set)
    heights: dict[uint32, bytes32] = field(default_factory=dict)

    # BlocksProtocol
    async def lookup_block_generators(self, header_hash: bytes32, generator_refs: set[uint32]) -> dict[uint32, bytes]:
        raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)  # pragma: no cover

    async def get_block_record_from_db(self, header_hash: bytes32) -> BlockRecord | None:
        return None  # pragma: no cover

    def add_block_record(self, block_record: BlockRecord) -> None:
        self.added_blocks.add(block_record.header_hash)

    # BlockRecordsProtocol
    def try_block_record(self, header_hash: bytes32) -> BlockRecord | None:
        return None  # pragma: no cover

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        raise KeyError("no block records in NullBlockchain")  # pragma: no cover

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        raise ValueError("Height is not in blockchain")

    def height_to_hash(self, height: uint32) -> bytes32 | None:
        return self.heights.get(height)

    def contains_block(self, header_hash: bytes32, height: uint32) -> bool:
        return False  # pragma: no cover

    def contains_height(self, height: uint32) -> bool:
        return height in self.heights.keys()

    async def prev_block_hash(self, header_hashes: list[bytes32]) -> list[bytes32]:
        raise KeyError("no block records in NullBlockchain")  # pragma: no cover


class InMemoryBlockchain:
    if TYPE_CHECKING:
        from chia.consensus.blockchain_interface import BlocksProtocol

        _protocol_check: ClassVar[BlocksProtocol] = cast("InMemoryBlockchain", None)

    def __init__(self) -> None:
        self._cache = BlockCache({})
        self.added_blocks: set[bytes32] = set()

    @property
    def heights(self) -> dict[uint32, bytes32]:
        return self._cache._height_to_hash

    # BlocksProtocol (non-BlockRecordsProtocol methods)
    async def lookup_block_generators(self, header_hash: bytes32, generator_refs: set[uint32]) -> dict[uint32, bytes]:
        raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)  # pragma: no cover

    async def get_block_record_from_db(self, header_hash: bytes32) -> BlockRecord | None:
        return self._cache.try_block_record(header_hash)

    def add_block_record(self, block_record: BlockRecord) -> None:
        self.added_blocks.add(block_record.header_hash)
        self._cache.add_block(block_record)

    # BlockRecordsProtocol — delegate to BlockCache
    def try_block_record(self, header_hash: bytes32) -> BlockRecord | None:
        return self._cache.try_block_record(header_hash)

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self._cache.block_record(header_hash)

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        return self._cache.height_to_block_record(height)

    def height_to_hash(self, height: uint32) -> bytes32 | None:
        return self._cache.height_to_hash(height)

    def contains_block(self, header_hash: bytes32, height: uint32) -> bool:
        return self._cache.contains_block(header_hash, height)

    def contains_height(self, height: uint32) -> bool:
        return self._cache.contains_height(height)

    async def prev_block_hash(self, header_hashes: list[bytes32]) -> list[bytes32]:
        return await self._cache.prev_block_hash(header_hashes)


@dataclass
class BlockchainMock(NullBlockchain):
    records: dict[bytes32, BlockRecord] = field(default_factory=dict)

    async def get_block_record_from_db(self, header_hash: bytes32) -> BlockRecord | None:
        return self.records.get(header_hash)

    def add_block_record(self, block_record: BlockRecord) -> None:
        self.added_blocks.add(block_record.header_hash)
        self.records[block_record.header_hash] = block_record
        self.heights[block_record.height] = block_record.header_hash

    def try_block_record(self, header_hash: bytes32) -> BlockRecord | None:
        return self.records.get(header_hash)

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self.records[header_hash]

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        hh = self.heights.get(height)
        if hh is None:
            raise ValueError("Height is not in blockchain")
        return self.records[hh]

    def contains_block(self, header_hash: bytes32, height: uint32) -> bool:
        return self.heights.get(height) == header_hash

    async def prev_block_hash(self, header_hashes: list[bytes32]) -> list[bytes32]:
        ret: list[bytes32] = []
        for hh in header_hashes:
            br = self.records.get(hh)
            if br is None:
                raise KeyError("no block records in BlockchainMock")
            ret.append(br.prev_hash)
        return ret


@dataclass
class SparseCacheBlockchainMock(BlockchainMock):
    cached_hashes: set[bytes32] = field(default_factory=set)

    def try_block_record(self, header_hash: bytes32) -> BlockRecord | None:
        if header_hash not in self.cached_hashes:
            return None
        return super().try_block_record(header_hash)


@dataclass
class FakeBlockRecord:
    height: uint32
    header_hash: bytes32
    prev_hash: bytes32


def BR(b: FullBlock) -> BlockRecord:
    ret = FakeBlockRecord(b.height, b.header_hash, b.prev_header_hash)
    return ret  # type: ignore[return-value]


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_augmented_chain(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks
    # this test blockchain is expected to have block generators at these
    # heights:
    # 2, 3, 4, 5, 6, 7, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
    # 24, 25, 26, 28

    null = NullBlockchain()
    abc = AugmentedBlockchain(null)

    # before adding anything to the augmented blockchain, make sure we just pass
    # through all requests
    with pytest.raises(ValueError, match="Height is not in blockchain"):
        abc.height_to_block_record(uint32(1))

    with pytest.raises(KeyError):
        abc.block_record(blocks[2].header_hash)

    with pytest.raises(KeyError):
        await abc.prev_block_hash([blocks[2].header_hash])

    with pytest.raises(ValueError, match=re.escape(Err.GENERATOR_REF_HAS_NO_GENERATOR.name)):
        await abc.lookup_block_generators(blocks[3].header_hash, {uint32(3)})

    block_records = []

    # now add some blocks
    for b in blocks[:5]:
        block_records.append(BR(b))
        abc.add_extra_block(b, BR(b))

    assert abc.height_to_block_record(uint32(1)) == block_records[1]

    with pytest.raises(ValueError, match=re.escape(Err.GENERATOR_REF_HAS_NO_GENERATOR.name)):
        await abc.lookup_block_generators(blocks[10].header_hash, {uint32(3), uint32(10)})

    # block 1 exists in the chain, but it doesn't have a generator
    with pytest.raises(ValueError, match=re.escape(Err.GENERATOR_REF_HAS_NO_GENERATOR.name)):
        await abc.lookup_block_generators(blocks[1].header_hash, {uint32(1)})

    expect_gen = blocks[2].transactions_generator
    assert expect_gen is not None
    assert await abc.lookup_block_generators(blocks[5].prev_header_hash, {uint32(2)}) == {uint32(2): bytes(expect_gen)}

    for i in range(1, 5):
        assert await abc.prev_block_hash([blocks[i].header_hash]) == [blocks[i - 1].header_hash]

    for i in range(5):
        assert abc.block_record(blocks[i].header_hash) == block_records[i]
        assert abc.try_block_record(blocks[i].header_hash) == block_records[i]
        assert abc.height_to_hash(uint32(i)) == blocks[i].header_hash
        assert await abc.prev_block_hash([blocks[i].header_hash]) == [blocks[i].prev_header_hash]
        assert abc.try_block_record(blocks[i].header_hash) is not None
        assert await abc.get_block_record_from_db(blocks[i].header_hash) == block_records[i]
        assert abc.contains_height(uint32(i))

    for i in range(5, 10):
        assert abc.height_to_hash(uint32(i)) is None
        assert abc.try_block_record(blocks[i].header_hash) is None
        assert not await abc.get_block_record_from_db(blocks[i].header_hash)
        assert not abc.contains_height(uint32(i))

    assert abc.height_to_hash(uint32(5)) is None
    null.heights = {uint32(5): blocks[5].header_hash}
    assert abc.height_to_hash(uint32(5)) is None

    # if we add blocks to cache that are already augmented into the chain, the
    # augmented blocks should be removed
    assert len(abc._extra_blocks) == 5
    for b in blocks[:5]:
        abc.add_block_record(BR(b))
    assert len(abc._extra_blocks) == 0
    assert null.added_blocks == {br.header_hash for br in blocks[:5]}


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_augmented_chain_contains_block(default_10000_blocks: list[FullBlock], bt: BlockTools) -> None:
    blocks = default_10000_blocks[:50]
    async with create_blockchain(bt.constants, 2) as (b1, _):
        async with create_blockchain(bt.constants, 2) as (b2, _):
            for block in blocks:
                await _validate_and_add_block(b1, block)
                await _validate_and_add_block(b2, block)

            new_blocks = bt.get_consecutive_blocks(10, block_list_input=blocks)[50:]
            abc = AugmentedBlockchain(b1)
            for block in new_blocks:
                await _validate_and_add_block(b2, block)
                block_rec = b2.block_record(block.header_hash)
                abc.add_extra_block(block, block_rec)

            for block in blocks:
                # check underlying contains block but augmented does not
                assert abc.contains_block(block.header_hash, block.height) is True
                assert block.height not in abc._height_to_hash

            for block in new_blocks:
                # check augmented contains block but augmented does not
                assert abc.contains_block(block.header_hash, block.height) is True
                assert not abc._underlying.contains_height(block.height)

            for block in new_blocks:
                await _validate_and_add_block(b1, block)

            for block in new_blocks:
                # check underlying contains block
                assert abc._underlying.height_to_hash(block.height) == block.header_hash
                # check augmented contains block
                assert abc._height_to_hash[block.height] == block.header_hash

            abc.remove_extra_block(new_blocks[-1].header_hash)

            # check blocks removed from augmented
            for block in new_blocks:
                # check underlying contains block
                assert abc._underlying.height_to_hash(block.height) == block.header_hash
                # check augmented contains block
                assert block.height not in abc._height_to_hash


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_augmented_chain_sequential(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks[:10]
    abc = AugmentedBlockchain(NullBlockchain())

    # wrong header_hash in block_record
    abc.add_extra_block(blocks[0], BR(blocks[0]))
    mismatched_record = FakeBlockRecord(
        height=uint32(1),
        header_hash=blocks[2].header_hash,
        prev_hash=blocks[0].header_hash,
    )
    with pytest.raises(AugmentedBlockchainValidationError, match="Block header hash mismatch"):
        abc.add_extra_block(blocks[1], mismatched_record)  # type: ignore[arg-type]

    abc.add_extra_block(blocks[1], BR(blocks[1]))

    # out of order
    with pytest.raises(AugmentedBlockchainValidationError, match="New block's prev_hash must match last added block"):
        abc.add_extra_block(blocks[3], BR(blocks[3]))

    # wrong prev_hash
    wrong_prev_block = FakeBlockRecord(
        height=uint32(2),
        header_hash=blocks[2].header_hash,
        prev_hash=blocks[0].header_hash,  # Points to block 0 instead of block 1
    )

    with pytest.raises(AugmentedBlockchainValidationError, match="New block's prev_hash must match last added block"):
        abc.add_extra_block(blocks[2], wrong_prev_block)  # type: ignore[arg-type]

    abc.add_extra_block(blocks[2], BR(blocks[2]))
    assert len(abc._height_to_hash) == 3


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_augmented_chain_validation_first_block_prev_hash(
    default_10000_blocks: list[FullBlock], bt: BlockTools
) -> None:
    blocks = default_10000_blocks[:50]
    async with create_blockchain(bt.constants, 2) as (blockchain, _):
        for block in blocks[:10]:
            await _validate_and_add_block(blockchain, block)

        # first block prev_hash not in underlying
        abc = AugmentedBlockchain(blockchain)
        fake_prev_hash = bytes32(b"0" * 32)
        orphan_block = FakeBlockRecord(
            height=uint32(100),
            header_hash=blocks[20].header_hash,
            prev_hash=fake_prev_hash,  # Doesn't exist in underlying
        )

        with pytest.raises(
            AugmentedBlockchainValidationError, match="First added block's prev_hash must exist in underlying"
        ):
            abc.add_extra_block(blocks[20], orphan_block)  # type: ignore[arg-type]

        abc2 = AugmentedBlockchain(blockchain)
        correct_block = FakeBlockRecord(
            height=uint32(10),
            header_hash=blocks[10].header_hash,
            prev_hash=blocks[9].header_hash,  # Block 9 is in underlying peak
        )
        abc2.add_extra_block(blocks[10], correct_block)  # type: ignore[arg-type]
        assert len(abc2._height_to_hash) == 1


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_remove_promoted_extra_block_cascades(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks
    underlying = InMemoryBlockchain()
    underlying.add_block_record(BR(blocks[1]))
    abc = AugmentedBlockchain(underlying)

    abc.add_extra_block(blocks[2], BR(blocks[2]))
    br5 = FakeBlockRecord(height=uint32(5), header_hash=blocks[5].header_hash, prev_hash=blocks[2].header_hash)
    abc.add_extra_block(blocks[5], br5)  # type: ignore[arg-type]

    underlying.heights[uint32(2)] = blocks[2].header_hash
    underlying.heights[uint32(5)] = blocks[5].header_hash

    # block 2 is now in the underlying, so removing it triggers cascade
    abc.remove_extra_block(blocks[2].header_hash)

    assert uint32(2) not in abc._height_to_hash
    assert uint32(5) in abc._height_to_hash
    assert abc._fork_height == uint32(2)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_remove_non_promoted_extra_block(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks
    underlying = InMemoryBlockchain()
    underlying.add_block_record(BR(blocks[1]))
    abc = AugmentedBlockchain(underlying)

    abc.add_extra_block(blocks[2], BR(blocks[2]))

    br5 = FakeBlockRecord(height=uint32(5), header_hash=blocks[5].header_hash, prev_hash=blocks[2].header_hash)
    abc.add_extra_block(blocks[5], br5)  # type: ignore[arg-type]

    br7 = FakeBlockRecord(height=uint32(7), header_hash=blocks[7].header_hash, prev_hash=blocks[5].header_hash)
    abc.add_extra_block(blocks[7], br7)  # type: ignore[arg-type]

    underlying.heights[uint32(5)] = blocks[5].header_hash
    underlying.heights[uint32(7)] = blocks[7].header_hash

    # block 5 is in the underlying, so cascade fires downward from height 5
    # but stops at height 4 (gap in _height_to_hash)
    abc.remove_extra_block(blocks[5].header_hash)

    assert uint32(5) not in abc._height_to_hash
    assert uint32(7) in abc._height_to_hash


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_gap_below_fork_point_uses_underlying(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks
    underlying = BlockchainMock()
    for block in blocks[:4]:
        underlying.add_block_record(BR(block))

    abc = AugmentedBlockchain(underlying)
    abc.add_extra_block(blocks[2], BR(blocks[2]))
    abc.add_extra_block(blocks[3], BR(blocks[3]))

    # Underlying height lookup disagrees with records to verify gap resolution.
    underlying.heights[uint32(1)] = bytes32(b"\xff" * 32)

    abc.remove_extra_block(blocks[2].header_hash)

    assert abc.height_to_hash(uint32(1)) == bytes32(b"\xff" * 32)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_hash_lookup_underlying_cache_miss(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks
    underlying = SparseCacheBlockchainMock()
    for block in blocks[:4]:
        underlying.add_block_record(BR(block))

    underlying.cached_hashes = {blocks[3].header_hash}
    abc = AugmentedBlockchain(underlying)
    abc.add_block_record(BR(blocks[3]))
    abc.add_extra_block(blocks[4], BR(blocks[4]))

    assert underlying.try_block_record(blocks[2].header_hash) is None
    assert abc.height_to_hash(uint32(1)) == blocks[1].header_hash


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_promoted_orphan_below_fork_uses_underlying(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks
    underlying = BlockchainMock()
    for block in blocks[:4]:
        underlying.add_block_record(BR(block))

    abc = AugmentedBlockchain(underlying)
    # simulate an augmented orphan record promoted into underlying DB/cache
    abc.add_block_record(BR(blocks[3]))
    assert len(abc._extra_blocks) == 0

    # Under the fork point, underlying height lookup is trusted directly.
    underlying.heights[uint32(1)] = bytes32(b"\xff" * 32)
    assert abc.height_to_hash(uint32(1)) == bytes32(b"\xff" * 32)


@pytest.mark.anyio
async def test_fork_height_stays_fixed_for_augmented_branch() -> None:
    h0 = bytes32(b"\x00" * 32)
    h1 = bytes32(b"\x01" * 32)
    h2 = bytes32(b"\x02" * 32)
    h3 = bytes32(b"\x03" * 32)

    underlying = BlockchainMock()
    underlying.add_block_record(FakeBlockRecord(height=uint32(0), header_hash=h0, prev_hash=h0))  # type: ignore[arg-type]
    underlying.add_block_record(FakeBlockRecord(height=uint32(1), header_hash=h1, prev_hash=h0))  # type: ignore[arg-type]

    abc = AugmentedBlockchain(underlying)
    abc.add_block_record(FakeBlockRecord(height=uint32(2), header_hash=h2, prev_hash=h1))  # type: ignore[arg-type]

    assert abc._fork_height == uint32(1)

    # Promote another block on the same augmented branch; fork point stays fixed.
    abc.add_block_record(FakeBlockRecord(height=uint32(3), header_hash=h3, prev_hash=h2))  # type: ignore[arg-type]
    assert abc._fork_height == uint32(1)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_orphan_gap_resolved_by_traversal(default_10000_blocks: list[FullBlock]) -> None:
    """Blocks between the fork point and the lowest augmented height exist as
    orphans in the underlying (in its block-record cache but NOT in its
    height-to-hash map).  height_to_hash must resolve them by backward
    traversal from the lowest augmented block, not by delegating to the
    underlying which would return the wrong (canonical) hash."""
    blocks = default_10000_blocks

    underlying = BlockchainMock()
    for block in blocks[:5]:
        underlying.add_block_record(BR(block))
    # canonical heights: {0: h0, 1: h1, 2: h2, 3: h3, 4: h4}

    # Orphan fork blocks at heights 3-4 that branch from canonical height 2.
    fork_h3 = blocks[10].header_hash
    fork_h4 = blocks[11].header_hash
    fork_h5 = blocks[12].header_hash
    underlying.records[fork_h3] = FakeBlockRecord(uint32(3), fork_h3, blocks[2].header_hash)  # type: ignore[arg-type]
    underlying.records[fork_h4] = FakeBlockRecord(uint32(4), fork_h4, fork_h3)  # type: ignore[arg-type]
    # These are NOT in underlying.heights — they are orphans.

    abc = AugmentedBlockchain(underlying)
    abc.add_extra_block(
        blocks[12],
        FakeBlockRecord(uint32(5), fork_h5, fork_h4),  # type: ignore[arg-type]
    )

    # Fork point should be height 2 (where the fork ancestry meets canonical).
    assert abc._fork_height == uint32(2)

    # Case 1: in augmented height-to-hash.
    assert abc.height_to_hash(uint32(5)) == fork_h5

    # Case 2: at or below the fork point — underlying (canonical).
    assert abc.height_to_hash(uint32(0)) == blocks[0].header_hash
    assert abc.height_to_hash(uint32(1)) == blocks[1].header_hash
    assert abc.height_to_hash(uint32(2)) == blocks[2].header_hash

    # Case 3: orphan gap — resolved by traversal, NOT the underlying.
    assert abc.height_to_hash(uint32(3)) == fork_h3
    assert abc.height_to_hash(uint32(4)) == fork_h4

    # Above the augmented chain's tip: no data.
    assert abc.height_to_hash(uint32(6)) is None


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_fork_height_advances_on_cascade(default_10000_blocks: list[FullBlock]) -> None:
    """When remove_extra_block triggers a cascade (fork promoted to canonical),
    _fork_height advances to the removed block's height."""
    blocks = default_10000_blocks

    underlying = BlockchainMock()
    for block in blocks[:5]:
        underlying.add_block_record(BR(block))

    fork_h3 = blocks[10].header_hash
    fork_h4 = blocks[11].header_hash
    fork_h5 = blocks[12].header_hash
    underlying.records[fork_h3] = FakeBlockRecord(uint32(3), fork_h3, blocks[2].header_hash)  # type: ignore[arg-type]
    underlying.records[fork_h4] = FakeBlockRecord(uint32(4), fork_h4, fork_h3)  # type: ignore[arg-type]

    abc = AugmentedBlockchain(underlying)
    abc.add_extra_block(
        blocks[12],
        FakeBlockRecord(uint32(5), fork_h5, fork_h4),  # type: ignore[arg-type]
    )
    assert abc._fork_height == uint32(2)

    # Promote the fork block at height 5 to canonical in the underlying.
    underlying.heights[uint32(5)] = fork_h5
    abc.remove_extra_block(fork_h5)

    # Fork height should advance to the promoted block's height.
    assert abc._fork_height == uint32(5)


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_read_only_snapshot_rejects_mutation(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks
    underlying = InMemoryBlockchain()
    underlying.add_block_record(BR(blocks[1]))
    abc = AugmentedBlockchain(underlying)
    abc.add_extra_block(blocks[2], BR(blocks[2]))

    snapshot = abc.read_only_snapshot()
    expected_error = "Cannot mutate read-only augmented blockchain snapshot"

    with pytest.raises(AugmentedBlockchainValidationError, match=expected_error):
        snapshot.remove_extra_block(blocks[2].header_hash)

    with pytest.raises(AugmentedBlockchainValidationError, match=expected_error):
        snapshot.add_block_record(BR(blocks[0]))

    br3 = FakeBlockRecord(height=uint32(3), header_hash=blocks[3].header_hash, prev_hash=blocks[2].header_hash)
    with pytest.raises(AugmentedBlockchainValidationError, match=expected_error):
        snapshot.add_extra_block(blocks[3], br3)  # type: ignore[arg-type]


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_read_only_snapshot_preserves_generator_lookup(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks
    underlying = InMemoryBlockchain()
    underlying.add_block_record(BR(blocks[1]))
    abc = AugmentedBlockchain(underlying)
    abc.add_extra_block(blocks[2], BR(blocks[2]))

    generator = blocks[2].transactions_generator
    assert generator is not None
    expected = {uint32(2): bytes(generator)}

    snapshot = abc.read_only_snapshot()
    assert await abc.lookup_block_generators(blocks[2].header_hash, {uint32(2)}) == expected
    assert await snapshot.lookup_block_generators(blocks[2].header_hash, {uint32(2)}) == expected


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(reason="save time")
async def test_read_only_snapshot_isolated_from_writer(default_10000_blocks: list[FullBlock]) -> None:
    blocks = default_10000_blocks
    underlying = InMemoryBlockchain()
    underlying.add_block_record(BR(blocks[1]))
    abc = AugmentedBlockchain(underlying)
    abc.add_extra_block(blocks[2], BR(blocks[2]))

    snapshot = abc.read_only_snapshot()
    assert snapshot.block_record(blocks[2].header_hash) == BR(blocks[2])

    br3 = FakeBlockRecord(height=uint32(3), header_hash=blocks[3].header_hash, prev_hash=blocks[2].header_hash)
    abc.add_extra_block(blocks[3], br3)  # type: ignore[arg-type]
    assert uint32(3) in abc._height_to_hash
    assert uint32(3) not in snapshot._height_to_hash
    assert snapshot.try_block_record(blocks[3].header_hash) is None
