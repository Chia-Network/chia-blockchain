from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from chia_rs import CoinRecord
from chia_rs.sized_bytes import bytes32

from chia.consensus.block_height_map_protocol import BlockHeightMapProtocol
from chia.consensus.block_store_protocol import BlockStoreProtocol
from chia.consensus.coin_store_protocol import CoinStoreProtocol


class ConsensusStoreWriter(Protocol):
    """
    Write operations available within a consensus store transaction.

    Entering the writer context manager starts a database transaction.
    All operations commit on successful exit, or roll back on exception.
    """

    @property
    def block_store(self) -> BlockStoreProtocol: ...

    @property
    def coin_store(self) -> CoinStoreProtocol: ...

    async def rollback_to_fork(self, fork_height: int) -> dict[bytes32, CoinRecord]:
        """
        Unified rollback across all stores. Within a single transaction:
        - Rolls back coin records (deletes coins confirmed above fork_height,
          un-spends coins spent above fork_height)
        - Marks blocks above fork_height as not in the main chain
          (sets in_main_chain=0)

        Returns the modified coin records.
        """
        ...


class ConsensusStoreProtocol(Protocol):
    """
    Protocol for the unified consensus store.

    Bundles block storage, coin storage, and the height map behind a single
    interface with transactional read and write access. The consensus layer
    uses this protocol so it does not depend on any specific storage backend.
    """

    @property
    def block_store(self) -> BlockStoreProtocol: ...

    @property
    def coin_store(self) -> CoinStoreProtocol: ...

    @property
    def height_map(self) -> BlockHeightMapProtocol: ...

    def writer(self) -> AbstractAsyncContextManager[ConsensusStoreWriter]:
        """
        Returns an async context manager that starts a write transaction.
        All writes performed through the yielded writer are atomic.
        On successful exit the transaction commits; on exception it rolls back.
        """
        ...

    def reader(self) -> AbstractAsyncContextManager[None]:
        """
        Returns an async context manager that establishes a consistent
        read snapshot. Useful when multiple reads must see a consistent
        view of the database.
        """
        ...
