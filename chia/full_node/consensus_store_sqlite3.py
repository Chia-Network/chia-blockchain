from __future__ import annotations

import contextlib
import dataclasses
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, cast

import typing_extensions
from chia_rs import CoinRecord
from chia_rs.sized_bytes import bytes32

from chia.consensus.block_height_map import BlockHeightMap
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.util.db_version import lookup_db_version, set_db_version_async
from chia.util.db_wrapper import DBWrapper2, manage_connection


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
    _hint_store: HintStore
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
        hint_store = await HintStore.create(db_wrapper)
        return cls(
            _block_store=block_store,
            _coin_store=coin_store,
            _height_map=height_map,
            _hint_store=hint_store,
            _db_wrapper=db_wrapper,
        )

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(
        cls,
        database: Path,
        *,
        blockchain_dir: Path | None = None,
        selected_network: str | None = None,
        reader_count: int = 4,
        log_path: Path | None = None,
        synchronous: str | None = None,
        use_block_cache: bool = True,
    ) -> AsyncIterator[ConsensusStoreSQLite3]:
        if blockchain_dir is None:
            blockchain_dir = database.parent

        async with manage_connection(database, name="version_check") as db_connection:
            db_version = await lookup_db_version(db_connection)

        async with DBWrapper2.managed(
            database,
            db_version=db_version,
            reader_count=reader_count,
            log_path=log_path,
            synchronous=synchronous,
        ) as db_wrapper:
            if db_wrapper.db_version != 2:
                async with db_wrapper.reader_no_transaction() as conn:
                    async with conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='full_blocks'"
                    ) as cur:
                        if len(list(await cur.fetchall())) == 0:
                            try:
                                async with db_wrapper.writer_maybe_transaction() as w_conn:
                                    await set_db_version_async(w_conn, 2)
                                    db_wrapper.db_version = 2
                            except sqlite3.OperationalError:
                                pass

            store = await cls.create(
                db_wrapper,
                blockchain_dir=blockchain_dir,
                selected_network=selected_network,
                use_block_cache=use_block_cache,
            )
            yield store

    @property
    def block_store(self) -> BlockStore:
        return self._block_store

    @property
    def coin_store(self) -> CoinStore:
        return self._coin_store

    @property
    def height_map(self) -> BlockHeightMap:
        return self._height_map

    @property
    def hint_store(self) -> HintStore:
        return self._hint_store

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
