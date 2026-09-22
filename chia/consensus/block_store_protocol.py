from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
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


@dataclass(frozen=True)
class MMRState:
    """
    Singleton metadata describing the persisted canonical header MMR.

    `canonical_height`/`canonical_header_hash` identify the canonical peak the
    persisted MMR was written for; they are used on startup to detect a stale
    store (one written for a different peak). `leaf_count` is the number of MMR
    leaves (post-`aggregate_from` canonical blocks); the flat node count must be
    `2 * leaf_count - popcount(leaf_count)`.
    """

    aggregate_from: uint32
    leaf_count: uint32
    canonical_height: uint32
    canonical_header_hash: bytes32


class MMRStoreProtocol(Protocol):
    """
    Persistence boundary for the canonical header MMR (post-HF2 composite
    leaves). The flat node array is stored so historical MMR states are implicit
    prefixes; only canonical appends and reorg truncations modify it, and they
    do so within the enclosing block-store write transaction so the persisted
    MMR commits atomically with the canonical peak change.
    """

    async def get_state(self) -> MMRState | None: ...

    async def get_nodes(self) -> list[bytes32]:
        """Return the full flat node array, ordered by position."""
        ...

    async def apply_canonical_update(self, truncation: int, new_nodes: list[bytes32], state: MMRState) -> None:
        """
        Persist a canonical MMR update: drop every node at flat position
        >= `truncation`, insert `new_nodes` starting at `truncation`, and store
        the new singleton `state`. Must be called within the enclosing
        block-store write transaction.
        """
        ...
