from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from chia_rs import BlockRecord, FullBlock, SubEpochChallengeSegment
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32


class BlockStoreProtocol(Protocol):
    """
    The block store interface used by `chia.consensus`.
    This is a substitute for importing from chia.full_node.block_store directly.

    The concrete `BlockStore` has a larger surface (block blobs by range,
    compactification queries, etc.), but those methods serve peer sync and
    RPCs, not consensus, so they are not part of this protocol.
    """

    async def add_full_block(self, header_hash: bytes32, block: FullBlock, block_record: BlockRecord) -> None: ...

    async def get_block_record(self, header_hash: bytes32) -> BlockRecord | None: ...

    async def get_block_records_by_hash(self, header_hashes: list[bytes32]) -> list[BlockRecord]: ...

    async def get_block_records_in_range(self, start: int, stop: int) -> dict[bytes32, BlockRecord]: ...

    async def get_block_records_close_to_peak(
        self, blocks_n: int
    ) -> tuple[dict[bytes32, BlockRecord], bytes32 | None]: ...

    async def get_prev_hash(self, header_hash: bytes32) -> bytes32: ...

    async def get_full_block(self, header_hash: bytes32) -> FullBlock | None: ...

    async def get_blocks_by_hash(self, header_hashes: list[bytes32]) -> list[FullBlock]: ...

    async def get_generator(self, header_hash: bytes32) -> bytes | None: ...

    async def get_generators_at(self, heights: set[uint32]) -> dict[uint32, bytes]: ...

    async def rollback(self, height: int) -> None: ...

    async def set_in_chain(self, header_hashes: list[tuple[bytes32]]) -> None: ...

    async def set_peak(self, header_hash: bytes32) -> None: ...

    def transaction(self) -> AbstractAsyncContextManager[None]:
        """
        A write transaction scope. Store methods called within the scope are
        atomic. The context manager deliberately yields None: the underlying
        database connection is an implementation detail of the store.
        """
        ...

    def get_block_from_cache(self, header_hash: bytes32) -> FullBlock | None: ...

    def rollback_cache_block(self, header_hash: bytes32) -> None: ...

    async def persist_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32, segments: list[SubEpochChallengeSegment]
    ) -> None: ...

    async def get_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32
    ) -> list[SubEpochChallengeSegment] | None: ...
