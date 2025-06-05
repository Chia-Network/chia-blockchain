from __future__ import annotations

from collections.abc import Collection
from typing import Optional, Protocol

<<<<<<< HEAD
from chia_rs import CoinState
=======
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
<<<<<<< HEAD
from chia.types.mempool_item import UnspentLineageInfo
=======
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)


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
<<<<<<< HEAD
        tx_additions: Collection[tuple[bytes32, Coin]],
=======
        tx_additions: Collection[Coin],
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)
        tx_removals: list[bytes32],
    ) -> None:
        """
        Add a new block to the coin store
        """
<<<<<<< HEAD
=======
        pass
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)

    async def get_coin_record(self, coin_id: bytes32) -> Optional[CoinRecord]:
        """
        Returns the coin record for the specified coin id
        """
<<<<<<< HEAD
=======
        pass
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)

    async def get_coin_records(self, coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        """
        Returns the coin records for the specified coin ids
        """
<<<<<<< HEAD
=======
        pass
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)

    async def get_coins_added_at_height(self, height: uint32) -> list[CoinRecord]:
        """
        Returns the coins added at a specific height
        """
<<<<<<< HEAD
=======
        pass
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
        """
        Returns the coins removed at a specific height
        """
<<<<<<< HEAD
=======
        pass
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)

    async def get_coin_records_by_puzzle_hash(
        self,
        include_spent_coins: bool,
        puzzle_hash: bytes32,
<<<<<<< HEAD
        start_height: uint32 = ...,
        end_height: uint32 = ...,
=======
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)
    ) -> list[CoinRecord]:
        """
        Returns the coin records for a specific puzzle hash
        """
<<<<<<< HEAD
=======
        pass
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)

    async def get_coin_records_by_puzzle_hashes(
        self,
        coins: bool,
        puzzle_hashes: list[bytes32],
<<<<<<< HEAD
        start_height: uint32 = ...,
        end_height: uint32 = ...,
=======
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)
    ) -> list[CoinRecord]:
        """
        Returns the coin records for a list of puzzle hashes
        """
<<<<<<< HEAD
=======
        pass
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)

    async def get_coin_records_by_names(
        self,
        include_spent_coins: bool,
        names: list[bytes32],
<<<<<<< HEAD
        start_height: uint32 = ...,
        end_height: uint32 = ...,
=======
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)
    ) -> list[CoinRecord]:
        """
        Returns the coin records for a list of coin names
        """
<<<<<<< HEAD

    async def get_coin_states_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: set[bytes32],
        min_height: uint32 = uint32(0),
        *,
        max_items: int = ...,
    ) -> set[CoinState]:
        """
        Returns the coin states for a set of puzzle hashes
        """
=======
        pass
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)

    async def get_coin_records_by_parent_ids(
        self,
        include_spent_coins: bool,
        parent_ids: list[bytes32],
<<<<<<< HEAD
        start_height: uint32 = ...,
        end_height: uint32 = ...,
=======
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)
    ) -> list[CoinRecord]:
        """
        Returns the coin records for a list of parent ids
        """
<<<<<<< HEAD

    async def get_coin_states_by_ids(
        self,
        include_spent_coins: bool,
        coin_ids: Collection[bytes32],
        min_height: uint32 = uint32(0),
        *,
        max_height: uint32 = ...,
        max_items: int = ...,
    ) -> list[CoinState]:
        """
        Returns the coin states for a collection of coin ids
        """

    async def batch_coin_states_by_puzzle_hashes(
        self,
        puzzle_hashes: list[bytes32],
        *,
        min_height: uint32 = ...,
        include_spent: bool = ...,
        include_unspent: bool = ...,
        include_hinted: bool = ...,
        min_amount: uint64 = ...,
        max_items: int = ...,
    ) -> tuple[list[CoinState], Optional[uint32]]:
        """
        Returns the coin states, as well as the next block height (or `None` if finished).
        """

    async def get_unspent_lineage_info_for_puzzle_hash(self, puzzle_hash: bytes32) -> Optional[UnspentLineageInfo]:
        """
        Lookup the most recent unspent lineage that matches a puzzle hash
        """

    async def rollback_to_block(self, block_index: int) -> dict[bytes32, CoinRecord]:
        """
        Rolls back the blockchain to the specified block index
        """

    # DEPRECATED: do not use in new code
    async def is_empty(self) -> bool:
        """
        Returns True if the coin store is empty
        """
=======
        pass

    async def rollback_to_block(self, block_index: int) -> list[CoinRecord]:
        """
        Rolls back the blockchain to the specified block index
        """
        pass
>>>>>>> e33e8b631 (Use `Protocol` instead of `ABC`.)
