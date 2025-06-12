from __future__ import annotations

from collections.abc import Collection
from typing import Optional, Protocol

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord


class CoinStoreProtocol(Protocol):
    """
    Protocol defining the interface for CoinStore.
    This is a substitute for importing from chia.full_node.coin_store directly.
    """

    async def new_block(
        self,
        height: uint32,
        timestamp: uint64,
        included_reward_coins: Collection[Coin],
        tx_additions: Collection[Coin],
        tx_removals: list[bytes32],
    ) -> None:
        """
        Add a new block to the coin store
        """
        pass

    async def get_coin_record(self, coin_id: bytes32) -> Optional[CoinRecord]:
        """
        Returns the coin record for the specified coin id
        """
        pass

    async def get_coin_records(self, coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        """
        Returns the coin records for the specified coin ids
        """
        pass

    async def get_coins_added_at_height(self, height: uint32) -> list[CoinRecord]:
        """
        Returns the coins added at a specific height
        """
        pass

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
        """
        Returns the coins removed at a specific height
        """
        pass

    async def get_coin_records_by_puzzle_hash(
        self,
        include_spent_coins: bool,
        puzzle_hash: bytes32,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        """
        Returns the coin records for a specific puzzle hash
        """
        pass

    async def get_coin_records_by_puzzle_hashes(
        self,
        coins: bool,
        puzzle_hashes: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        """
        Returns the coin records for a list of puzzle hashes
        """
        pass

    async def get_coin_records_by_names(
        self,
        include_spent_coins: bool,
        names: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        """
        Returns the coin records for a list of coin names
        """
        pass

    async def get_coin_records_by_parent_ids(
        self,
        include_spent_coins: bool,
        parent_ids: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]:
        """
        Returns the coin records for a list of parent ids
        """
        pass

    async def rollback_to_block(self, block_index: int) -> list[CoinRecord]:
        """
        Rolls back the blockchain to the specified block index
        """
        pass
