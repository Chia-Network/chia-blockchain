from __future__ import annotations

from collections.abc import Collection
from typing import Protocol

from chia_rs import CoinRecord
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.coin import Coin


class CoinStoreProtocol(Protocol):
    """
    The coin store interface used by `chia.consensus`.
    This is a substitute for importing from chia.full_node.coin_store directly.

    The concrete `CoinStore` has a much larger surface (puzzle hash queries,
    coin states, lineage lookups, etc.), but those methods serve RPCs and the
    wallet protocol, not consensus, so they are not part of this protocol.
    """

    async def new_block(
        self,
        height: uint32,
        timestamp: uint64,
        included_reward_coins: Collection[Coin],
        tx_additions: Collection[tuple[bytes32, Coin, bool]],
        tx_removals: list[bytes32],
    ) -> None:
        """
        Add a new block to the coin store
        """

    async def get_coin_records(self, coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        """
        Returns the coin records for the specified coin ids
        """

    async def get_coins_added_at_height(self, height: uint32) -> list[CoinRecord]:
        """
        Returns the coins added at a specific height
        """

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
        """
        Returns the coins removed at a specific height
        """

    async def rollback_to_block(self, block_index: int) -> dict[bytes32, CoinRecord]:
        """
        Rolls back the blockchain to the specified block index
        """
