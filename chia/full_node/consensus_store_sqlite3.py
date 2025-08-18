from __future__ import annotations

import dataclasses
from collections.abc import Collection
from contextlib import AbstractAsyncContextManager
from typing import Any, AsyncIterator, Optional, TYPE_CHECKING
from types import TracebackType

from chia_rs import BlockRecord, FullBlock, SubEpochChallengeSegment, SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.consensus.block_height_map import BlockHeightMap
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord


class ConsensusStoreSQLite3Writer:
    def __init__(self, block_store: BlockStore, coin_store: CoinStore):
        self._block_store = block_store
        self._coin_store = coin_store

    async def add_full_block(self, header_hash: bytes32, block: FullBlock, block_record: BlockRecord) -> None:
        await self._block_store.add_full_block(header_hash, block, block_record)

    async def rollback(self, height: int) -> None:
        await self._block_store.rollback(height)

    async def set_in_chain(self, header_hashes: list[tuple[bytes32]]) -> None:
        await self._block_store.set_in_chain(header_hashes)

    async def set_peak(self, header_hash: bytes32) -> None:
        await self._block_store.set_peak(header_hash)

    async def persist_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32, segments: list[SubEpochChallengeSegment]
    ) -> None:
        await self._block_store.persist_sub_epoch_challenge_segments(ses_block_hash, segments)

    async def rollback_to_block(self, block_index: int) -> dict[bytes32, CoinRecord]:
        return await self._coin_store.rollback_to_block(block_index)

    async def new_block(
        self,
        height: uint32,
        timestamp: uint64,
        included_reward_coins: Collection[Coin],
        tx_additions: Collection[tuple[bytes32, Coin, bool]],
        tx_removals: list[bytes32],
    ) -> None:
        await self._coin_store.new_block(height, timestamp, included_reward_coins, tx_additions, tx_removals)


@dataclasses.dataclass
class ConsensusStoreSQLite3:
    """
    Consensus store that combines block_store, coin_store, and height_map functionality.
    """

    block_store: BlockStore
    coin_store: CoinStore
    height_map: BlockHeightMap

    # Writer context and writer facade for transactional writes (re-entrant via depth counter)
    _writer_ctx: Optional[AbstractAsyncContextManager[Any]] = None
    _writer: Optional[Any] = None
    _txn_depth: int = 0

    @classmethod
    async def create(
        cls,
        block_store: BlockStore,
        coin_store: CoinStore,
        height_map: BlockHeightMap,
    ) -> "ConsensusStoreSQLite3":
        """Create a new ConsensusStore instance from existing sub-stores.

        This factory does not create sub-stores. Construct BlockStore, CoinStore,
        and BlockHeightMap separately and pass them in here.
        """
        return cls(
            block_store=block_store,
            coin_store=coin_store,
            height_map=height_map,
        )

    # Async context manager yielding a writer for atomic writes
    async def __aenter__(self):
        # Re-entrant async context manager:
        # Begin a transaction only at the outermost level. CoinStore shares the same DB.
        if self._txn_depth == 0:
            self._writer_ctx = self.block_store.transaction()
            await self._writer_ctx.__aenter__()
            # Create writer facade bound to this transaction
            self._writer = ConsensusStoreSQLite3Writer(self.block_store, self.coin_store)
        self._txn_depth += 1
        return self._writer  # Return the same writer for nested contexts

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Optional[bool]:
        try:
            # Check if we're at the outermost level before decrementing
            if self._txn_depth == 1:
                # This is the outermost context, handle transaction exit
                if self._writer_ctx is not None:
                    return await self._writer_ctx.__aexit__(exc_type, exc, tb)
                return None
            else:
                # This is a nested context, just return None (don't suppress exceptions)
                return None
        finally:
            # Always decrement depth and clean up if we're at the outermost level
            if self._txn_depth > 0:
                self._txn_depth -= 1
            if self._txn_depth == 0:
                self._writer_ctx = None
                self._writer = None

    # Block store methods

    async def get_block_records_close_to_peak(
        self, blocks_n: int
    ) -> tuple[dict[bytes32, BlockRecord], Optional[bytes32]]:
        return await self.block_store.get_block_records_close_to_peak(blocks_n)

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return await self.block_store.get_full_block(header_hash)

    async def get_block_records_by_hash(self, header_hashes: list[bytes32]) -> list[BlockRecord]:
        return await self.block_store.get_block_records_by_hash(header_hashes)

    async def get_block_records_in_range(self, start: int, stop: int) -> dict[bytes32, BlockRecord]:
        return await self.block_store.get_block_records_in_range(start, stop)

    def get_block_from_cache(self, header_hash: bytes32) -> Optional[FullBlock]:
        return self.block_store.get_block_from_cache(header_hash)

    async def get_blocks_by_hash(self, header_hashes: list[bytes32]) -> list[FullBlock]:
        return await self.block_store.get_blocks_by_hash(header_hashes)

    async def get_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        return await self.block_store.get_block_record(header_hash)

    async def get_prev_hash(self, header_hash: bytes32) -> bytes32:
        return await self.block_store.get_prev_hash(header_hash)

    async def get_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32
    ) -> Optional[list[SubEpochChallengeSegment]]:
        return await self.block_store.get_sub_epoch_challenge_segments(ses_block_hash)

    async def get_generator(self, header_hash: bytes32) -> Optional[bytes]:
        return await self.block_store.get_generator(header_hash)

    async def get_generators_at(self, heights: set[uint32]) -> dict[uint32, bytes]:
        return await self.block_store.get_generators_at(heights)

    # Coin store methods
    async def get_coin_records(self, names: Collection[bytes32]) -> list[CoinRecord]:
        return await self.coin_store.get_coin_records(names)

    async def get_coins_added_at_height(self, height: uint32) -> list[CoinRecord]:
        return await self.coin_store.get_coins_added_at_height(height)

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
        return await self.coin_store.get_coins_removed_at_height(height)

    def get_block_heights_in_main_chain(self) -> AsyncIterator[int]:
        async def gen():
            async with self.block_store.transaction() as conn:
                async with conn.execute("SELECT height, in_main_chain FROM full_blocks") as cursor:
                    async for row in cursor:
                        if row[1]:
                            yield row[0]

        return gen()

    # Height map methods
    def get_ses_heights(self) -> list[uint32]:
        return self.height_map.get_ses_heights()

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self.height_map.get_ses(height)

    def contains_height(self, height: uint32) -> bool:
        return self.height_map.contains_height(height)

    def get_hash(self, height: uint32) -> bytes32:
        return self.height_map.get_hash(height)

    def rollback_height_map(self, height: uint32) -> None:
        # BlockHeightMap.rollback is synchronous
        self.height_map.rollback(height)

    def update_height_map(self, height: uint32, block_hash: bytes32, ses: Optional[SubEpochSummary]) -> None:
        # BlockHeightMap exposes update_height(height, header_hash, ses)
        self.height_map.update_height(height, block_hash, ses)

    async def maybe_flush_height_map(self) -> None:
        # BlockHeightMap.maybe_flush is asynchronous
        await self.height_map.maybe_flush()

    def rollback_cache_block(self, header_hash: bytes32) -> None:
        self.block_store.rollback_cache_block(header_hash)


if TYPE_CHECKING:
    from typing import cast
    from chia.consensus.consensus_store_protocol import ConsensusStoreProtocol

    def _protocol_check(o: ConsensusStoreProtocol) -> None: ...

    _protocol_check(cast(ConsensusStoreSQLite3, None))
