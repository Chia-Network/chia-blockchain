from __future__ import annotations

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.util.db_connection import DBConnection, PathDBConnection
from chia.consensus.coinbase import create_farmer_coin, create_pool_coin
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.util.db_wrapper import DBWrapper2

# black box tests from `chia/_tests/core/full_node/stores/test_coin_store.py`
# should be moved here


async def add_block_to_store(
    db_wrapper: DBWrapper2, block_store: BlockStore, coin_store: CoinStore, height: uint32, tx_removals: list[bytes32]
) -> bytes32:
    """
    Advance the stores by one block: coins in the coin store, plus a minimal
    main-chain entry and peak update in the block store. The peak physically
    lives in the block store's tables today, so we write just enough of a
    `full_blocks` row for `get_peak()` to resolve the height (building real
    blocks is not needed to exercise the coin store).
    """
    header_hash = bytes32([height % 256] * 32)
    genesis_challenge = bytes32(b"\0" * 32)
    pool_coin = create_pool_coin(height, bytes32(b"\x01" * 32), uint64(1_750_000_000_000), genesis_challenge)
    farmer_coin = create_farmer_coin(height, bytes32(b"\x02" * 32), uint64(250_000_000_000), genesis_challenge)
    await coin_store.new_block(
        height=height,
        timestamp=uint64(1234567890 + height),
        included_reward_coins=[pool_coin, farmer_coin],
        tx_additions=[],
        tx_removals=tx_removals,
    )
    async with db_wrapper.writer_maybe_transaction() as conn:
        await conn.execute(
            "INSERT INTO full_blocks(header_hash, height, in_main_chain) VALUES(?, ?, 1)",
            (header_hash, height),
        )
    await block_store.set_peak(header_hash)
    return header_hash


@pytest.mark.anyio
async def test_snapshot_empty_db() -> None:
    async with PathDBConnection(2) as db_wrapper:
        block_store = await BlockStore.create(db_wrapper)
        coin_store = await CoinStore.create(db_wrapper, block_store=block_store)
        async with coin_store.snapshot() as snapshot:
            assert snapshot.peak() is None
            assert await snapshot.get_coin_records([bytes32(b"\x03" * 32)]) == []
            assert await snapshot.get_coins_added_at_height(uint32(1)) == []
            assert await snapshot.get_coins_removed_at_height(uint32(1)) == []


@pytest.mark.anyio
async def test_snapshot_requires_block_store() -> None:
    async with DBConnection(2) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        with pytest.raises(RuntimeError, match="block_store"):
            async with coin_store.snapshot():
                pass  # pragma: no cover


@pytest.mark.anyio
async def test_snapshot_is_consistent_across_writes() -> None:
    """
    Writes committed after a snapshot is acquired must not become visible
    inside it: the snapshot's peak and coin reads stay a consistent pair.
    This is sqlite WAL snapshot isolation on the read transaction the
    snapshot holds open (hence the file-backed database here; the in-memory
    test database does not support WAL).
    """
    async with PathDBConnection(2) as db_wrapper:
        block_store = await BlockStore.create(db_wrapper)
        coin_store = await CoinStore.create(db_wrapper, block_store=block_store)

        hash_1 = await add_block_to_store(db_wrapper, block_store, coin_store, uint32(1), [])
        [record_1, _] = await coin_store.get_coins_added_at_height(uint32(1))

        async with coin_store.snapshot() as snapshot:
            assert snapshot.peak() == (uint32(1), hash_1)

            # advance the chain while the snapshot is held: spend a height-1
            # coin and move the peak to height 2
            hash_2 = await add_block_to_store(db_wrapper, block_store, coin_store, uint32(2), [record_1.coin.name()])

            # the snapshot still answers as of acquisition
            assert snapshot.peak() == (uint32(1), hash_1)
            assert await snapshot.get_coins_added_at_height(uint32(2)) == []
            assert await snapshot.get_coins_removed_at_height(uint32(2)) == []
            [snapshot_record] = await snapshot.get_coin_records([record_1.coin.name()])
            assert not snapshot_record.spent

        # a snapshot acquired after the writes sees them
        async with coin_store.snapshot() as snapshot:
            assert snapshot.peak() == (uint32(2), hash_2)
            assert len(await snapshot.get_coins_added_at_height(uint32(2))) == 2
            [removed_record] = await snapshot.get_coins_removed_at_height(uint32(2))
            assert removed_record.coin.name() == record_1.coin.name()
            [record] = await snapshot.get_coin_records([record_1.coin.name()])
            assert record.spent


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
