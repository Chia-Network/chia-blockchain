from typing import Protocol, Optional, List, Set, Dict, Tuple
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.ints import uint32, uint64

class CoinStoreProtocol(Protocol):
    async def get_coin_record(self, coin_name: bytes32) -> Optional[CoinRecord]:
        """Returns the CoinRecord for given coin id if it exists"""
        ...

    async def get_coin_records(self, coin_names: List[bytes32]) -> List[CoinRecord]:
        """Returns the CoinRecords for given coin ids that exist in the store"""
        ...

    async def get_coins_added_at_height(self, height: uint32) -> List[CoinRecord]:
        """Returns list of CoinRecords for coins added at a specific height"""
        ...

    async def get_coins_removed_at_height(self, height: uint32) -> List[CoinRecord]:
        """Returns list of CoinRecords for coins removed at a specific height"""
        ...

    async def get_all_coins(self, include_spent_coins: bool) -> List[CoinRecord]:
        """Returns all CoinRecords in the store, optionally including spent coins"""
        ...

    async def get_coin_records_by_puzzle_hash(
        self,
        puzzle_hash: bytes32,
        include_spent_coins: bool = True,
        start_height: uint32 = 0,
        end_height: uint32 = 0,
    ) -> List[CoinRecord]:
        """Returns CoinRecords with given puzzle hash, optionally filtered by height range"""
        ...

    async def get_coin_records_by_puzzle_hashes(
        self,
        puzzle_hashes: List[bytes32],
        include_spent_coins: bool = True,
        start_height: uint32 = 0,
        end_height: uint32 = 0,
    ) -> List[CoinRecord]:
        """Returns CoinRecords with given puzzle hashes, optionally filtered by height range"""
        ...

    async def get_coin_records_by_parent_ids(
        self,
        parent_ids: List[bytes32],
        include_spent_coins: bool = True,
        start_height: uint32 = 0,
        end_height: uint32 = 0,
    ) -> List[CoinRecord]:
        """Returns CoinRecords with given parent ids, optionally filtered by height range"""
        ...

    async def rollback_to_block(self, height: int) -> None:
        """Rolls back the coin store to the given height"""
        ...

    async def get_unspent_coins_for_wallet(self, wallet_id: int) -> Set[Coin]:
        """Returns unspent coins for a specific wallet"""
        ...

    async def get_coin_state(
        self,
        coins: List[bytes32],
        last_height: uint32,
    ) -> Dict[bytes32, Tuple[Optional[CoinRecord], Optional[CoinRecord]]]:
        """Returns coin state (both spent and unspent records) for given coins up to last_height"""
        ...
