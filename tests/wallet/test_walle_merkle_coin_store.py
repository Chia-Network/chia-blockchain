from __future__ import annotations

from secrets import token_bytes

import pytest

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.util.merkle_utils import MerkleCoinType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_merkle_coin_record import WalletMerkleCoinRecord
from chia.wallet.wallet_merkle_coin_store import WalletMerkleCoinStore
from tests.util.db_connection import DBConnection

coin_1 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
coin_2 = Coin(coin_1.parent_coin_info, token_bytes(32), uint64(12311))
coin_3 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
coin_4 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
coin_5 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
coin_6 = Coin(token_bytes(32), coin_4.puzzle_hash, uint64(12312))
coin_7 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
record_replaced = WalletMerkleCoinRecord(
    coin_1,
    uint32(8),
    uint32(0),
    False,
    MerkleCoinType.CLAWBACK.value,
    '{"time_lock": 50}',
    WalletType.STANDARD_WALLET,
    0,
)
record_1 = WalletMerkleCoinRecord(
    coin_1,
    uint32(4),
    uint32(0),
    False,
    MerkleCoinType.CLAWBACK.value,
    '{"time_lock": 50}',
    WalletType.STANDARD_WALLET,
    0,
)
record_2 = WalletMerkleCoinRecord(
    coin_2,
    uint32(5),
    uint32(0),
    False,
    MerkleCoinType.CLAWBACK.value,
    '{"time_lock": 50}',
    WalletType.STANDARD_WALLET,
    0,
)
record_3 = WalletMerkleCoinRecord(
    coin_3,
    uint32(5),
    uint32(10),
    True,
    MerkleCoinType.CLAWBACK.value,
    '{"time_lock": 50}',
    WalletType.STANDARD_WALLET,
    0,
)
record_4 = WalletMerkleCoinRecord(
    coin_4,
    uint32(5),
    uint32(15),
    True,
    MerkleCoinType.CLAWBACK.value,
    '{"time_lock": 50}',
    WalletType.STANDARD_WALLET,
    0,
)
record_5 = WalletMerkleCoinRecord(
    coin_5,
    uint32(5),
    uint32(0),
    False,
    MerkleCoinType.CLAWBACK.value,
    '{"time_lock": 50}',
    WalletType.STANDARD_WALLET,
    1,
)
record_6 = WalletMerkleCoinRecord(
    coin_6,
    uint32(5),
    uint32(15),
    True,
    MerkleCoinType.CLAWBACK.value,
    '{"time_lock": 50}',
    WalletType.STANDARD_WALLET,
    2,
)
record_7 = WalletMerkleCoinRecord(
    coin_7,
    uint32(5),
    uint32(0),
    False,
    MerkleCoinType.CLAWBACK.value,
    '{"time_lock": 50}',
    WalletType.POOLING_WALLET,
    2,
)


@pytest.mark.asyncio
async def test_add_replace_get() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletMerkleCoinStore.create(db_wrapper)

        assert await store.get_coin_record(coin_1.name()) is None
        await store.add_coin_record(record_1)

        # adding duplicates is fine, we replace existing entry
        await store.add_coin_record(record_replaced)

        await store.add_coin_record(record_2)
        await store.add_coin_record(record_3)
        await store.add_coin_record(record_4)
        assert await store.get_coin_record(coin_1.name()) == record_replaced


@pytest.mark.asyncio
async def test_persistance() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletMerkleCoinStore.create(db_wrapper)
        await store.add_coin_record(record_1)

        store = await WalletMerkleCoinStore.create(db_wrapper)
        assert await store.get_coin_record(coin_1.name()) == record_1


@pytest.mark.asyncio
async def test_bulk_get() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletMerkleCoinStore.create(db_wrapper)
        await store.add_coin_record(record_1)
        await store.add_coin_record(record_2)
        await store.add_coin_record(record_3)
        await store.add_coin_record(record_4)

        store = await WalletMerkleCoinStore.create(db_wrapper)
        records = await store.get_coin_records(
            [coin_1.name(), coin_2.name(), bytes32.from_bytes(token_bytes(32)), coin_4.name()]
        )
        assert len(records) == 4
        assert records[0] == record_1
        assert records[1] == record_2
        assert records[2] is None
        assert records[3] == record_4


@pytest.mark.asyncio
async def test_set_spent() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletMerkleCoinStore.create(db_wrapper)
        await store.add_coin_record(record_1)
        coin_record = await store.get_coin_record(coin_1.name())
        assert coin_record is not None
        assert not coin_record.spent
        await store.set_spent(coin_1.name(), uint32(12))
        coin_record = await store.get_coin_record(coin_1.name())
        assert coin_record is not None
        assert coin_record.spent
        assert coin_record.spent_block_height == 12


@pytest.mark.asyncio
async def test_get_unspent_coins_for_wallet() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletMerkleCoinStore.create(db_wrapper)

        assert await store.get_unspent_coins_for_wallet(1) == set()

        await store.add_coin_record(record_4)  # this is spent and wallet 0
        await store.add_coin_record(record_5)  # wallet 1
        await store.add_coin_record(record_6)  # this is spent and wallet 2
        await store.add_coin_record(record_7)  # wallet 2

        assert await store.get_unspent_coins_for_wallet(1) == set([record_5])
        assert await store.get_unspent_coins_for_wallet(2) == set([record_7])
        assert await store.get_unspent_coins_for_wallet(3) == set()

        await store.set_spent(coin_4.name(), uint32(12))

        assert await store.get_unspent_coins_for_wallet(1) == set([record_5])
        assert await store.get_unspent_coins_for_wallet(2) == set([record_7])
        assert await store.get_unspent_coins_for_wallet(3) == set()

        await store.set_spent(coin_7.name(), uint32(12))

        assert await store.get_unspent_coins_for_wallet(1) == set([record_5])
        assert await store.get_unspent_coins_for_wallet(2) == set()
        assert await store.get_unspent_coins_for_wallet(3) == set()

        await store.set_spent(coin_5.name(), uint32(12))

        assert await store.get_unspent_coins_for_wallet(1) == set()
        assert await store.get_unspent_coins_for_wallet(2) == set()
        assert await store.get_unspent_coins_for_wallet(3) == set()


@pytest.mark.asyncio
async def test_get_all_unspent_coins() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletMerkleCoinStore.create(db_wrapper)

        assert await store.get_all_unspent_coins() == set()

        await store.add_coin_record(record_1)  # not spent
        await store.add_coin_record(record_2)  # not spent
        await store.add_coin_record(record_3)  # spent
        assert await store.get_all_unspent_coins() == set([record_1, record_2])

        await store.add_coin_record(record_4)  # spent
        await store.add_coin_record(record_5)  # not spent
        await store.add_coin_record(record_6)  # spent
        assert await store.get_all_unspent_coins() == set([record_1, record_2, record_5])

        await store.add_coin_record(record_7)  # not spent
        assert await store.get_all_unspent_coins() == set([record_1, record_2, record_5, record_7])

        await store.set_spent(coin_4.name(), uint32(12))
        assert await store.get_all_unspent_coins() == set([record_1, record_2, record_5, record_7])

        await store.set_spent(coin_7.name(), uint32(12))
        assert await store.get_all_unspent_coins() == set([record_1, record_2, record_5])

        await store.set_spent(coin_5.name(), uint32(12))
        assert await store.get_all_unspent_coins() == set([record_1, record_2])

        await store.set_spent(coin_2.name(), uint32(12))
        await store.set_spent(coin_1.name(), uint32(12))
        assert await store.get_all_unspent_coins() == set()


def record(c: Coin, *, confirmed: int, spent: int) -> WalletMerkleCoinRecord:
    return WalletMerkleCoinRecord(
        c,
        uint32(confirmed),
        uint32(spent),
        spent != 0,
        MerkleCoinType.CLAWBACK.value,
        '{"time_lock": 50}',
        WalletType.STANDARD_WALLET,
        0,
    )


@pytest.mark.asyncio
async def test_rollback_to_block() -> None:
    r1 = record(coin_1, confirmed=1, spent=0)
    r2 = record(coin_2, confirmed=2, spent=4)
    r3 = record(coin_3, confirmed=3, spent=5)
    r4 = record(coin_4, confirmed=4, spent=6)
    r5 = record(coin_5, confirmed=5, spent=7)

    async with DBConnection(1) as db_wrapper:
        store = await WalletMerkleCoinStore.create(db_wrapper)

        await store.add_coin_record(r1)
        await store.add_coin_record(r2)
        await store.add_coin_record(r3)
        await store.add_coin_record(r4)
        await store.add_coin_record(r5)

        assert set(
            (
                await store.get_coin_records(
                    [
                        coin_1.name(),
                        coin_2.name(),
                        coin_3.name(),
                        coin_4.name(),
                        coin_5.name(),
                    ]
                )
            )
        ) == set(
            [
                r1,
                r2,
                r3,
                r4,
                r5,
            ]
        )

        assert await store.get_coin_record(coin_5.name()) == r5

        await store.rollback_to_block(6)

        new_r5 = await store.get_coin_record(coin_5.name())
        assert new_r5 is not None
        assert not new_r5.spent
        assert new_r5.spent_block_height == 0
        assert new_r5 != r5

        assert await store.get_coin_record(coin_4.name()) == r4

        await store.rollback_to_block(4)

        assert await store.get_coin_record(coin_5.name()) is None
        new_r4 = await store.get_coin_record(coin_4.name())
        assert new_r4 is not None
        assert not new_r4.spent
        assert new_r4.spent_block_height == 0
        assert new_r4 != r4


@pytest.mark.asyncio
async def test_count_small_unspent() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletMerkleCoinStore.create(db_wrapper)

        coin_1 = Coin(token_bytes(32), token_bytes(32), uint64(1))
        coin_2 = Coin(token_bytes(32), token_bytes(32), uint64(2))
        coin_3 = Coin(token_bytes(32), token_bytes(32), uint64(4))

        r1 = record(coin_1, confirmed=1, spent=0)
        r2 = record(coin_2, confirmed=2, spent=0)
        r3 = record(coin_3, confirmed=3, spent=0)

        await store.add_coin_record(r1)
        await store.add_coin_record(r2)
        await store.add_coin_record(r3)

        assert await store.count_small_unspent(5) == 3
        assert await store.count_small_unspent(4) == 2
        assert await store.count_small_unspent(3) == 2
        assert await store.count_small_unspent(2) == 1
        assert await store.count_small_unspent(1) == 0

        await store.set_spent(coin_2.name(), uint32(12))

        assert await store.count_small_unspent(5) == 2
        assert await store.count_small_unspent(4) == 1
        assert await store.count_small_unspent(3) == 1
        assert await store.count_small_unspent(2) == 1
        assert await store.count_small_unspent(1) == 0
