from __future__ import annotations

from typing import Optional, Protocol

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord


class CoinStoreProtocol(Protocol):
    async def get_coin_record(self, coin_name: bytes32) -> Optional[CoinRecord]:
        """Returns the CoinRecord for given coin id if it exists"""
        ...

    async def get_coin_records(self, coin_names: list[bytes32]) -> list[CoinRecord]:
        """Returns the CoinRecords for given coin ids that exist in the store"""
        ...

    async def get_coins_added_at_height(self, height: uint32) -> list[CoinRecord]:
        """Returns list of CoinRecords for coins added at a specific height"""
        ...

    async def get_coins_removed_at_height(self, height: uint32) -> list[CoinRecord]:
        """Returns list of CoinRecords for coins removed at a specific height"""
        ...

    async def get_all_coins(self, include_spent_coins: bool) -> list[CoinRecord]:
        """Returns all CoinRecords in the store, optionally including spent coins"""
        ...

    async def get_coin_records_by_puzzle_hash(
        self,
        puzzle_hash: bytes32,
        include_spent_coins: bool = True,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32(0),
    ) -> list[CoinRecord]:
        """Returns CoinRecords with given puzzle hash, optionally filtered by height range"""
        ...

    async def get_coin_records_by_puzzle_hashes(
        self,
        puzzle_hashes: list[bytes32],
        include_spent_coins: bool = True,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32(0),
    ) -> list[CoinRecord]:
        """Returns CoinRecords with given puzzle hashes, optionally filtered by height range"""
        ...

    async def get_coin_records_by_parent_ids(
        self,
        parent_ids: list[bytes32],
        include_spent_coins: bool = True,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32(0),
    ) -> list[CoinRecord]:
        """Returns CoinRecords with given parent ids, optionally filtered by height range"""
        ...

    async def rollback_to_block(self, height: int) -> None:
        """Rolls back the coin store to the given height"""
        ...

    async def get_unspent_coins_for_wallet(self, wallet_id: int) -> set[Coin]:
        """Returns unspent coins for a specific wallet"""
        ...

    async def get_coin_state(
        self,
        coins: list[bytes32],
        last_height: uint32,
    ) -> dict[bytes32, tuple[Optional[CoinRecord], Optional[CoinRecord]]]:
        """Returns coin state (both spent and unspent records) for given coins up to last_height"""
        ...
