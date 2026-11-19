from __future__ import annotations

from collections.abc import Collection
from typing import Protocol

from chia_rs import CoinRecord, CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.mempool_item import UnspentLineageInfo


class ExplorerStoreProtocol(Protocol):
    """
    The queries that serve RPCs, the wallet protocol and the mempool's
    singleton fast forward: coins by puzzle hash and parent, coin states,
    lineage, and hints. Consensus does not use these.
    """

    async def get_coin_records_by_puzzle_hash(
        self,
        include_spent_coins: bool,
        puzzle_hash: bytes32,
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]: ...

    async def get_coin_records_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]: ...

    async def get_coin_records_by_names(
        self,
        include_spent_coins: bool,
        names: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
    ) -> list[CoinRecord]: ...

    async def get_coin_states_by_puzzle_hashes(
        self,
        include_spent_coins: bool,
        puzzle_hashes: set[bytes32],
        min_height: uint32 = uint32(0),
        *,
        max_items: int = 50000,
    ) -> set[CoinState]: ...

    async def get_coin_records_by_parent_ids(
        self,
        include_spent_coins: bool,
        parent_ids: list[bytes32],
        start_height: uint32 = uint32(0),
        end_height: uint32 = uint32((2**32) - 1),
        *,
        max_items: int = 50000,
    ) -> list[CoinRecord]: ...

    async def get_coin_states_by_ids(
        self,
        include_spent_coins: bool,
        coin_ids: Collection[bytes32],
        min_height: uint32 = uint32(0),
        *,
        max_height: uint32 = uint32.MAXIMUM,
        max_items: int = 50000,
    ) -> list[CoinState]: ...

    async def batch_coin_states_by_puzzle_hashes(
        self,
        puzzle_hashes: list[bytes32],
        *,
        min_height: uint32 = uint32(0),
        include_spent: bool = True,
        include_unspent: bool = True,
        include_hinted: bool = True,
        min_amount: uint64 = uint64(0),
        max_items: int = 50000,
    ) -> tuple[list[CoinState], uint32 | None]: ...

    async def get_unspent_lineage_info_for_puzzle_hash(self, puzzle_hash: bytes32) -> UnspentLineageInfo | None: ...

    async def get_coin_ids(self, hint: bytes, *, max_items: int = 50000) -> list[bytes32]: ...

    async def get_coin_ids_multi(self, hints: set[bytes], *, max_items: int = 50000) -> list[bytes32]: ...

    async def get_coin_ids_by_hints(self, hints: Collection[bytes]) -> set[bytes32]: ...

    async def get_hints(self, coin_ids: list[bytes32]) -> list[bytes32]: ...

    async def add_hints(self, coin_hint_list: list[tuple[bytes32, bytes]]) -> None: ...

    async def count_hints(self) -> int: ...
