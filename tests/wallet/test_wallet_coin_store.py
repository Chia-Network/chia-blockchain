from __future__ import annotations

from secrets import token_bytes

import pytest

from chia.types.blockchain_format.coin import Coin
from chia.util.ints import uint32, uint64
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import WalletCoinStore
from tests.util.db_connection import DBConnection

coin_1 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
coin_2 = Coin(coin_1.parent_coin_info, token_bytes(32), uint64(12311))
coin_3 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
coin_4 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
coin_5 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
coin_6 = Coin(token_bytes(32), coin_4.puzzle_hash, uint64(12312))
coin_7 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
record_replaced = WalletCoinRecord(coin_1, uint32(8), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
record_1 = WalletCoinRecord(coin_1, uint32(4), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
record_2 = WalletCoinRecord(coin_2, uint32(5), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
record_3 = WalletCoinRecord(
    coin_3,
    uint32(5),
    uint32(10),
    True,
    False,
    WalletType.STANDARD_WALLET,
    0,
)
record_4 = WalletCoinRecord(
    coin_4,
    uint32(5),
    uint32(15),
    True,
    False,
    WalletType.STANDARD_WALLET,
    0,
)
record_5 = WalletCoinRecord(
    coin_5,
    uint32(5),
    uint32(0),
    False,
    False,
    WalletType.STANDARD_WALLET,
    1,
)
record_6 = WalletCoinRecord(
    coin_6,
    uint32(5),
    uint32(15),
    True,
    False,
    WalletType.STANDARD_WALLET,
    2,
)
record_7 = WalletCoinRecord(
    coin_7,
    uint32(5),
    uint32(0),
    False,
    False,
    WalletType.POOLING_WALLET,
    2,
)


@pytest.mark.asyncio
async def test_add_replace_get() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

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
        store = await WalletCoinStore.create(db_wrapper)
        await store.add_coin_record(record_1)

        store = await WalletCoinStore.create(db_wrapper)
        assert await store.get_coin_record(coin_1.name()) == record_1


@pytest.mark.asyncio
async def test_bulk_get() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)
        await store.add_coin_record(record_1)
        await store.add_coin_record(record_2)
        await store.add_coin_record(record_3)
        await store.add_coin_record(record_4)

        store = await WalletCoinStore.create(db_wrapper)
        records = await store.get_coin_records([coin_1.name(), coin_2.name(), token_bytes(32), coin_4.name()])
        assert records == [record_1, record_2, None, record_4]


@pytest.mark.asyncio
async def test_set_spent() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)
        await store.add_coin_record(record_1)

        assert not (await store.get_coin_record(coin_1.name())).spent
        await store.set_spent(coin_1.name(), uint32(12))
        assert (await store.get_coin_record(coin_1.name())).spent
        assert (await store.get_coin_record(coin_1.name())).spent_block_height == 12


@pytest.mark.asyncio
async def test_get_records_by_puzzle_hash() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        await store.add_coin_record(record_4)
        await store.add_coin_record(record_5)

        # adding duplicates is fine, we replace existing entry
        await store.add_coin_record(record_5)

        await store.add_coin_record(record_6)
        assert len(await store.get_coin_records_by_puzzle_hash(record_6.coin.puzzle_hash)) == 2  # 4 and 6
        assert len(await store.get_coin_records_by_puzzle_hash(token_bytes(32))) == 0

        assert await store.get_coin_record(coin_6.name()) == record_6
        assert await store.get_coin_record(token_bytes(32)) is None


@pytest.mark.asyncio
async def test_get_unspent_coins_for_wallet() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

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
        store = await WalletCoinStore.create(db_wrapper)

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


@pytest.mark.asyncio
async def test_get_records_by_parent_id() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        await store.add_coin_record(record_1)
        await store.add_coin_record(record_2)
        await store.add_coin_record(record_3)
        await store.add_coin_record(record_4)
        await store.add_coin_record(record_5)
        await store.add_coin_record(record_6)
        await store.add_coin_record(record_7)

        assert set(await store.get_coin_records_by_parent_id(coin_1.parent_coin_info)) == set([record_1, record_2])
        assert set(await store.get_coin_records_by_parent_id(coin_2.parent_coin_info)) == set([record_1, record_2])
        assert await store.get_coin_records_by_parent_id(coin_3.parent_coin_info) == [record_3]
        assert await store.get_coin_records_by_parent_id(coin_4.parent_coin_info) == [record_4]
        assert await store.get_coin_records_by_parent_id(coin_5.parent_coin_info) == [record_5]
        assert await store.get_coin_records_by_parent_id(coin_6.parent_coin_info) == [record_6]
        assert await store.get_coin_records_by_parent_id(coin_7.parent_coin_info) == [record_7]


@pytest.mark.asyncio
async def test_get_multiple_coin_records() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        await store.add_coin_record(record_1)
        await store.add_coin_record(record_2)
        await store.add_coin_record(record_3)
        await store.add_coin_record(record_4)
        await store.add_coin_record(record_5)
        await store.add_coin_record(record_6)
        await store.add_coin_record(record_7)

        assert set(await store.get_multiple_coin_records([coin_1.name(), coin_2.name(), coin_3.name()])) == set(
            [record_1, record_2, record_3]
        )

        assert set(await store.get_multiple_coin_records([coin_5.name(), coin_6.name(), coin_7.name()])) == set(
            [record_5, record_6, record_7]
        )

        assert set(
            await store.get_multiple_coin_records(
                [
                    coin_1.name(),
                    coin_2.name(),
                    coin_3.name(),
                    coin_4.name(),
                    coin_5.name(),
                    coin_6.name(),
                    coin_7.name(),
                ]
            )
        ) == set([record_1, record_2, record_3, record_4, record_5, record_6, record_7])


@pytest.mark.asyncio
async def test_delete_coin_record() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        await store.add_coin_record(record_1)
        await store.add_coin_record(record_2)
        await store.add_coin_record(record_3)
        await store.add_coin_record(record_4)
        await store.add_coin_record(record_5)
        await store.add_coin_record(record_6)
        await store.add_coin_record(record_7)

        assert set(
            await store.get_multiple_coin_records(
                [
                    coin_1.name(),
                    coin_2.name(),
                    coin_3.name(),
                    coin_4.name(),
                    coin_5.name(),
                    coin_6.name(),
                    coin_7.name(),
                ]
            )
        ) == set([record_1, record_2, record_3, record_4, record_5, record_6, record_7])

        assert await store.get_coin_record(coin_1.name()) == record_1

        await store.delete_coin_record(coin_1.name())

        assert await store.get_coin_record(coin_1.name()) is None
        assert set(
            await store.get_multiple_coin_records(
                [coin_2.name(), coin_3.name(), coin_4.name(), coin_5.name(), coin_6.name(), coin_7.name()]
            )
        ) == set([record_2, record_3, record_4, record_5, record_6, record_7])


def record(c: Coin, *, confirmed: int, spent: int) -> WalletCoinRecord:
    return WalletCoinRecord(c, uint32(confirmed), uint32(spent), spent != 0, False, WalletType.STANDARD_WALLET, 0)


@pytest.mark.asyncio
async def test_get_coin_names_to_check() -> None:

    r1 = record(coin_1, confirmed=1, spent=0)
    r2 = record(coin_2, confirmed=2, spent=4)
    r3 = record(coin_3, confirmed=3, spent=5)
    r4 = record(coin_4, confirmed=4, spent=6)
    r5 = record(coin_5, confirmed=5, spent=7)
    # these spent heights violate the invariant
    r6 = record(coin_6, confirmed=6, spent=1)
    r7 = record(coin_7, confirmed=7, spent=2)

    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        await store.add_coin_record(r1)
        await store.add_coin_record(r2)
        await store.add_coin_record(r3)
        await store.add_coin_record(r4)
        await store.add_coin_record(r5)
        await store.add_coin_record(r6)
        await store.add_coin_record(r7)

        for i in range(10):

            coins = await store.get_coin_names_to_check(i)

            # r1 is unspent and should always be included, regardless of height
            assert r1.coin.name() in coins
            # r2 was spent at height 4
            assert (r2.coin.name() in coins) == (i < 4)
            # r3 was spent at height 5
            assert (r3.coin.name() in coins) == (i < 5)
            # r4 was spent at height 6
            assert (r4.coin.name() in coins) == (i < 6)
            # r5 was spent at height 7
            assert (r5.coin.name() in coins) == (i < 7)
            # r6 was confirmed at height 6
            assert (r6.coin.name() in coins) == (i < 6)
            # r7 was confirmed at height 7
            assert (r7.coin.name() in coins) == (i < 7)


@pytest.mark.asyncio
async def test_get_first_coin_height() -> None:

    r1 = record(coin_1, confirmed=1, spent=0)
    r2 = record(coin_2, confirmed=2, spent=4)
    r3 = record(coin_3, confirmed=3, spent=5)
    r4 = record(coin_4, confirmed=4, spent=6)
    r5 = record(coin_5, confirmed=5, spent=7)

    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        assert await store.get_first_coin_height() is None

        await store.add_coin_record(r5)
        assert await store.get_first_coin_height() == 5
        await store.add_coin_record(r4)
        assert await store.get_first_coin_height() == 4
        await store.add_coin_record(r3)
        assert await store.get_first_coin_height() == 3
        await store.add_coin_record(r2)
        assert await store.get_first_coin_height() == 2
        await store.add_coin_record(r1)
        assert await store.get_first_coin_height() == 1


@pytest.mark.asyncio
async def test_rollback_to_block() -> None:

    r1 = record(coin_1, confirmed=1, spent=0)
    r2 = record(coin_2, confirmed=2, spent=4)
    r3 = record(coin_3, confirmed=3, spent=5)
    r4 = record(coin_4, confirmed=4, spent=6)
    r5 = record(coin_5, confirmed=5, spent=7)

    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        await store.add_coin_record(r1)
        await store.add_coin_record(r2)
        await store.add_coin_record(r3)
        await store.add_coin_record(r4)
        await store.add_coin_record(r5)

        assert set(
            await store.get_multiple_coin_records(
                [
                    coin_1.name(),
                    coin_2.name(),
                    coin_3.name(),
                    coin_4.name(),
                    coin_5.name(),
                ]
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
        assert not new_r5.spent
        assert new_r5.spent_block_height == 0
        assert new_r5 != r5

        assert await store.get_coin_record(coin_4.name()) == r4

        await store.rollback_to_block(4)

        assert await store.get_coin_record(coin_5.name()) is None
        new_r4 = await store.get_coin_record(coin_4.name())
        assert not new_r4.spent
        assert new_r4.spent_block_height == 0
        assert new_r4 != r4


@pytest.mark.asyncio
async def test_count_small_unspent() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

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
