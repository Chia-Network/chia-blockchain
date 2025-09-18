from __future__ import annotations

from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from chia_rs import BlockRecord, FullBlock, SubEpochChallengeSegment, SubEpochSummary
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from typing_extensions import Self

from chia.consensus.block_height_map import BlockHeightMap
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
from chia.util.db_wrapper import DBWrapper2


@dataclass
class ConsensusStoreSQLite3Writer:
    block_store: BlockStore
    coin_store: CoinStore

    async def add_full_block(self, header_hash: bytes32, block: FullBlock, block_record: BlockRecord) -> None:
        await self.block_store.add_full_block(header_hash, block, block_record)

    async def rollback(self, height: int) -> None:
        await self.block_store.rollback(height)

    async def set_in_chain(self, header_hashes: list[tuple[bytes32]]) -> None:
        await self.block_store.set_in_chain(header_hashes)

    async def set_peak(self, header_hash: bytes32) -> None:
        await self.block_store.set_peak(header_hash)

    async def persist_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32, segments: list[SubEpochChallengeSegment]
    ) -> None:
        await self.block_store.persist_sub_epoch_challenge_segments(ses_block_hash, segments)

    async def rollback_to_block(self, block_index: int) -> dict[bytes32, CoinRecord]:
        return await self.coin_store.rollback_to_block(block_index)

    async def new_block(
        self,
        height: uint32,
        timestamp: uint64,
        included_reward_coins: Collection[Coin],
        tx_additions: Collection[tuple[bytes32, Coin, bool]],
        tx_removals: list[bytes32],
    ) -> None:
        await self.coin_store.new_block(height, timestamp, included_reward_coins, tx_additions, tx_removals)

    @asynccontextmanager
    async def writer(self) -> AsyncIterator[Self]:
        # Return self as the writer facade
        async with self.block_store.transaction():
            yield self


@dataclass
class ConsensusStoreSQLite3:
    """
    Consensus store that combines block_store, coin_store, and height_map functionality.
    """

    block_store: BlockStore
    coin_store: CoinStore
    height_map: BlockHeightMap

    @classmethod
    async def create(
        cls,
        db_wrapper: DBWrapper2,
        blockchain_dir: Path,
        *,
        use_cache: bool = True,
        selected_network: Optional[str] = None,
    ) -> ConsensusStoreSQLite3:
        """Create a new ConsensusStore instance, creating all underlying sub-stores internally.

        Args:
            db_wrapper: Database wrapper to use for all stores
            blockchain_dir: Directory path for blockchain data (used by BlockHeightMap)
            use_cache: Whether to enable caching in BlockStore (default: True)
            selected_network: Network selection for BlockHeightMap (default: None)
        """
        # Create underlying stores
        block_store = await BlockStore.create(db_wrapper, use_cache=use_cache)
        coin_store = await CoinStore.create(db_wrapper)
        height_map = await BlockHeightMap.create(blockchain_dir, db_wrapper, selected_network)

        return cls(
            block_store=block_store,
            coin_store=coin_store,
            height_map=height_map,
        )

    @asynccontextmanager
    async def writer(self) -> AsyncIterator[ConsensusStoreSQLite3Writer]:
        """Async context manager that yields a writer facade for performing transactional writes."""
        csw = ConsensusStoreSQLite3Writer(self.block_store, self.coin_store)
        async with csw.writer() as writer:
            yield writer

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

    async def get_coin_record(self, coin_name: bytes32) -> Optional[CoinRecord]:
        return await self.coin_store.get_coin_record(coin_name)

    async def get_coins_added_at_height(self, height: uint32) -> list[CoinRecord]:
        return await self.coin_store.get_coins_added_at_height(height)

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
        return await self.coin_store.get_coins_removed_at_height(height)

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
