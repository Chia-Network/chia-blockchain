from __future__ import annotations

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.util.db_connection import DBConnection
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.full_node.coin_store import CoinStore

# black box tests from `chia/_tests/core/full_node/stores/test_coin_store.py`
# should be moved here


@pytest.mark.anyio
async def test_is_empty_when_empty(db_version: int) -> None:
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        assert await coin_store.is_empty() is True


@pytest.mark.anyio
async def test_is_empty_when_not_empty(db_version: int) -> None:
    async with DBConnection(db_version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        assert await coin_store.is_empty() is True
        height = uint32(1)
        genesis_challenge = bytes32(b"\0" * 32)
        pool_puzzle_hash = bytes32(b"\x01" * 32)
        farmer_puzzle_hash = bytes32(b"\x02" * 32)
        pool_coin = create_pool_coin(height, pool_puzzle_hash, uint64(1_750_000_000_000), genesis_challenge)
        farmer_coin = create_farmer_coin(height, farmer_puzzle_hash, uint64(1_750_000_000_000), genesis_challenge)
        await coin_store.new_block(
            height=height,
            timestamp=uint64(1234567890),
            included_reward_coins=[pool_coin, farmer_coin],
            tx_additions=[],
            tx_removals=[],
        )
        assert await coin_store.is_empty() is False
