from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, cast

import typing_extensions
from chia_rs import CoinRecord
from chia_rs.sized_bytes import bytes32

from chia.consensus.block_height_map import BlockHeightMap
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.util.db_wrapper import DBWrapper2


@typing_extensions.final
@dataclasses.dataclass
class ConsensusStoreSQLite3Writer:
    _block_store: BlockStore
    _coin_store: CoinStore

    @property
    def block_store(self) -> BlockStore:
        return self._block_store

    @property
    def coin_store(self) -> CoinStore:
        return self._coin_store

    async def rollback_to_fork(self, fork_height: int) -> dict[bytes32, CoinRecord]:
        rolled_back = await self._coin_store.rollback_to_block(fork_height)
        await self._block_store.rollback(fork_height)
        return rolled_back


@typing_extensions.final
@dataclasses.dataclass
class ConsensusStoreSQLite3:
    _block_store: BlockStore
    _coin_store: CoinStore
    _height_map: BlockHeightMap
    _db_wrapper: DBWrapper2

    @classmethod
    async def create(
        cls,
        db_wrapper: DBWrapper2,
        blockchain_dir: Path = Path("."),
        selected_network: str | None = None,
        *,
        use_block_cache: bool = True,
    ) -> ConsensusStoreSQLite3:
        block_store = await BlockStore.create(db_wrapper, use_cache=use_block_cache)
        coin_store = await CoinStore.create(db_wrapper)
        height_map = await BlockHeightMap.create(blockchain_dir, db_wrapper, selected_network)
        return cls(
            _block_store=block_store,
            _coin_store=coin_store,
            _height_map=height_map,
            _db_wrapper=db_wrapper,
        )

    @property
    def block_store(self) -> BlockStore:
        return self._block_store

    @property
    def coin_store(self) -> CoinStore:
        return self._coin_store

    @property
    def height_map(self) -> BlockHeightMap:
        return self._height_map

    @contextlib.asynccontextmanager
    async def writer(self) -> AsyncIterator[ConsensusStoreSQLite3Writer]:
        async with self._db_wrapper.writer():
            yield ConsensusStoreSQLite3Writer(
                _block_store=self._block_store,
                _coin_store=self._coin_store,
            )

    @contextlib.asynccontextmanager
    async def reader(self) -> AsyncIterator[None]:
        async with self._db_wrapper.reader():
            yield


if TYPE_CHECKING:
    from chia.consensus.consensus_store import ConsensusStoreProtocol, ConsensusStoreWriter

    _store_check: ConsensusStoreProtocol = cast("ConsensusStoreSQLite3", None)
    _writer_check: ConsensusStoreWriter = cast("ConsensusStoreSQLite3Writer", None)
