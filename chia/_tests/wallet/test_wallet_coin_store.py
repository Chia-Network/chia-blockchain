from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

import pytest

from chia._tests.util.db_connection import DBConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.util.misc import UInt32Range, UInt64Range, VersionedBlob
from chia.util.streamable import Streamable
from chia.wallet.puzzles.clawback.metadata import ClawbackMetadata
from chia.wallet.util.query_filter import AmountFilter, HashFilter
from chia.wallet.util.wallet_types import CoinType, WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import CoinRecordOrder, GetCoinRecords, GetCoinRecordsResult, WalletCoinStore

clawback_metadata = ClawbackMetadata(uint64(0), bytes32(b"1" * 32), bytes32(b"2" * 32))

module_seeded_random = random.Random()
module_seeded_random.seed(a=0, version=2)

coin_1 = Coin(bytes32.random(module_seeded_random), bytes32.random(module_seeded_random), uint64(12312))
coin_2 = Coin(coin_1.parent_coin_info, bytes32.random(module_seeded_random), uint64(12311))
coin_3 = Coin(bytes32.random(module_seeded_random), bytes32.random(module_seeded_random), uint64(12312))
coin_4 = Coin(bytes32.random(module_seeded_random), bytes32.random(module_seeded_random), uint64(12312))
coin_5 = Coin(bytes32.random(module_seeded_random), bytes32.random(module_seeded_random), uint64(12312))
coin_6 = Coin(bytes32.random(module_seeded_random), coin_4.puzzle_hash, uint64(12312))
coin_7 = Coin(bytes32.random(module_seeded_random), bytes32.random(module_seeded_random), uint64(12312))
coin_8 = Coin(bytes32.random(module_seeded_random), bytes32.random(module_seeded_random), uint64(2))
coin_9 = Coin(coin_5.name(), bytes32.random(module_seeded_random), uint64(4))
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
record_8 = WalletCoinRecord(
    coin_8,
    uint32(1),
    uint32(0),
    False,
    False,
    WalletType.STANDARD_WALLET,
    1,
    CoinType.CLAWBACK,
    VersionedBlob(uint16(1), bytes(clawback_metadata)),
)
record_9 = WalletCoinRecord(
    coin_9,
    uint32(1),
    uint32(2),
    True,
    False,
    WalletType.STANDARD_WALLET,
    2,
    CoinType.CLAWBACK,
    VersionedBlob(uint16(1), bytes(clawback_metadata)),
)


def get_dummy_record(wallet_id: int, seeded_random: random.Random) -> WalletCoinRecord:
    return WalletCoinRecord(
        Coin(bytes32.random(seeded_random), bytes32.random(seeded_random), uint64(12312)),
        uint32(0),
        uint32(0),
        False,
        False,
        WalletType.STANDARD_WALLET,
        wallet_id,
    )


@dataclass
class DummyWalletCoinRecords:
    seeded_random: random.Random
    records_per_wallet: Dict[int, List[WalletCoinRecord]] = field(default_factory=dict)

    def generate(self, wallet_id: int, count: int) -> None:
        records = self.records_per_wallet.setdefault(wallet_id, [])
        for _ in range(count):
            records.append(get_dummy_record(wallet_id, seeded_random=self.seeded_random))


@pytest.mark.parametrize(
    "invalid_record, error",
    [
        (replace(record_8, metadata=None), "Can't parse None metadata"),
        (replace(record_8, coin_type=CoinType.NORMAL), "Unknown metadata"),
    ],
)
def test_wallet_coin_record_parsed_metadata_failures(invalid_record: WalletCoinRecord, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        invalid_record.parsed_metadata()


@pytest.mark.parametrize(
    "coin_record, expected_metadata",
    [
        (record_8, clawback_metadata),
    ],
)
def test_wallet_coin_record_parsed_metadata(coin_record: WalletCoinRecord, expected_metadata: Streamable) -> None:
    assert coin_record.parsed_metadata() == expected_metadata


@pytest.mark.parametrize("coin_record", [record_1, record_2, record_8])
def test_wallet_coin_record_json_parsed(coin_record: WalletCoinRecord) -> None:
    expected_metadata = None
    if coin_record.coin_type == CoinType.CLAWBACK:
        assert coin_record.metadata is not None
        expected_metadata = coin_record.parsed_metadata().to_json_dict()

    assert coin_record.to_json_dict_parsed_metadata() == {
        "id": "0x" + coin_record.name().hex(),
        "amount": coin_record.coin.amount,
        "puzzle_hash": "0x" + coin_record.coin.puzzle_hash.hex(),
        "parent_coin_info": "0x" + coin_record.coin.parent_coin_info.hex(),
        "type": coin_record.coin_type,
        "wallet_identifier": coin_record.wallet_identifier().to_json_dict(),
        "confirmed_height": coin_record.confirmed_block_height,
        "metadata": expected_metadata,
        "spent_height": coin_record.spent_block_height,
        "coinbase": coin_record.coinbase,
    }


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_persistance() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)
        await store.add_coin_record(record_1)

        store = await WalletCoinStore.create(db_wrapper)
        assert await store.get_coin_record(coin_1.name()) == record_1


@pytest.mark.anyio
async def test_set_spent() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)
        await store.add_coin_record(record_1)

        assert not (await store.get_coin_record(coin_1.name())).spent
        await store.set_spent(coin_1.name(), uint32(12))
        assert (await store.get_coin_record(coin_1.name())).spent
        assert (await store.get_coin_record(coin_1.name())).spent_block_height == 12


@pytest.mark.anyio
async def test_get_records_by_puzzle_hash(seeded_random: random.Random) -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        await store.add_coin_record(record_4)
        await store.add_coin_record(record_5)

        # adding duplicates is fine, we replace existing entry
        await store.add_coin_record(record_5)

        await store.add_coin_record(record_6)
        assert len(await store.get_coin_records_by_puzzle_hash(record_6.coin.puzzle_hash)) == 2  # 4 and 6
        assert len(await store.get_coin_records_by_puzzle_hash(bytes32.random(seeded_random))) == 0

        assert await store.get_coin_record(coin_6.name()) == record_6
        assert await store.get_coin_record(bytes32.random(seeded_random)) is None


@pytest.mark.anyio
async def test_get_unspent_coins_for_wallet() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        assert await store.get_unspent_coins_for_wallet(1) == set()

        await store.add_coin_record(record_4)  # this is spent and wallet 0
        await store.add_coin_record(record_5)  # wallet 1
        await store.add_coin_record(record_6)  # this is spent and wallet 2
        await store.add_coin_record(record_7)  # wallet 2
        await store.add_coin_record(record_8)

        assert await store.get_unspent_coins_for_wallet(1) == {record_5}
        assert await store.get_unspent_coins_for_wallet(2) == {record_7}
        assert await store.get_unspent_coins_for_wallet(3) == set()

        await store.set_spent(coin_4.name(), uint32(12))

        assert await store.get_unspent_coins_for_wallet(1) == {record_5}
        assert await store.get_unspent_coins_for_wallet(2) == {record_7}
        assert await store.get_unspent_coins_for_wallet(3) == set()

        await store.set_spent(coin_7.name(), uint32(12))

        assert await store.get_unspent_coins_for_wallet(1) == {record_5}
        assert await store.get_unspent_coins_for_wallet(2) == set()
        assert await store.get_unspent_coins_for_wallet(3) == set()

        await store.set_spent(coin_5.name(), uint32(12))

        assert await store.get_unspent_coins_for_wallet(1) == set()
        assert await store.get_unspent_coins_for_wallet(2) == set()
        assert await store.get_unspent_coins_for_wallet(3) == set()

        assert await store.get_unspent_coins_for_wallet(1, coin_type=CoinType.CLAWBACK) == {record_8}


@pytest.mark.anyio
async def test_get_all_unspent_coins() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        assert await store.get_all_unspent_coins() == set()

        await store.add_coin_record(record_1)  # not spent
        await store.add_coin_record(record_2)  # not spent
        await store.add_coin_record(record_3)  # spent
        await store.add_coin_record(record_8)  # spent
        assert await store.get_all_unspent_coins() == {record_1, record_2}

        await store.add_coin_record(record_4)  # spent
        await store.add_coin_record(record_5)  # not spent
        await store.add_coin_record(record_6)  # spent
        assert await store.get_all_unspent_coins() == {record_1, record_2, record_5}

        await store.add_coin_record(record_7)  # not spent
        assert await store.get_all_unspent_coins() == {record_1, record_2, record_5, record_7}

        await store.set_spent(coin_4.name(), uint32(12))
        assert await store.get_all_unspent_coins() == {record_1, record_2, record_5, record_7}

        await store.set_spent(coin_7.name(), uint32(12))
        assert await store.get_all_unspent_coins() == {record_1, record_2, record_5}

        await store.set_spent(coin_5.name(), uint32(12))
        assert await store.get_all_unspent_coins() == {record_1, record_2}

        await store.set_spent(coin_2.name(), uint32(12))
        await store.set_spent(coin_1.name(), uint32(12))
        assert await store.get_all_unspent_coins() == set()

        assert await store.get_all_unspent_coins(coin_type=CoinType.CLAWBACK) == {record_8}


@pytest.mark.anyio
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

        assert set(await store.get_coin_records_by_parent_id(coin_1.parent_coin_info)) == {record_1, record_2}
        assert set(await store.get_coin_records_by_parent_id(coin_2.parent_coin_info)) == {record_1, record_2}
        assert await store.get_coin_records_by_parent_id(coin_3.parent_coin_info) == [record_3]
        assert await store.get_coin_records_by_parent_id(coin_4.parent_coin_info) == [record_4]
        assert await store.get_coin_records_by_parent_id(coin_5.parent_coin_info) == [record_5]
        assert await store.get_coin_records_by_parent_id(coin_6.parent_coin_info) == [record_6]
        assert await store.get_coin_records_by_parent_id(coin_7.parent_coin_info) == [record_7]


@pytest.mark.anyio
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

        assert (
            await store.get_coin_records(
                coin_id_filter=HashFilter.include(
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
            )
        ).records == [record_1, record_2, record_3, record_4, record_5, record_6, record_7]

        assert await store.get_coin_record(coin_1.name()) == record_1

        await store.delete_coin_record(coin_1.name())

        assert await store.get_coin_record(coin_1.name()) is None
        assert (
            await store.get_coin_records(
                coin_id_filter=HashFilter.include(
                    [coin_2.name(), coin_3.name(), coin_4.name(), coin_5.name(), coin_6.name(), coin_7.name()]
                )
            )
        ).records == [record_2, record_3, record_4, record_5, record_6, record_7]


get_coin_records_offset_limit_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(offset=uint32(0), limit=uint32(0)), []),
    (GetCoinRecords(offset=uint32(10), limit=uint32(0)), []),
    (GetCoinRecords(offset=uint32(0), limit=uint32(1)), [record_8]),
    (GetCoinRecords(offset=uint32(1), limit=uint32(1)), [record_9]),
    (GetCoinRecords(offset=uint32(0), limit=uint32(2)), [record_8, record_9]),
    (GetCoinRecords(offset=uint32(0), limit=uint32(5)), [record_8, record_9, record_1, record_2, record_3]),
    (GetCoinRecords(coin_type=uint8(CoinType.CLAWBACK), offset=uint32(0), limit=uint32(5)), [record_8, record_9]),
    (GetCoinRecords(offset=uint32(2), limit=uint32(5)), [record_1, record_2, record_3, record_4, record_5]),
    (GetCoinRecords(coin_type=uint8(CoinType.CLAWBACK), offset=uint32(5), limit=uint32(1)), []),
]

get_coin_records_wallet_id_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (
        GetCoinRecords(),
        [record_8, record_9, record_1, record_2, record_3, record_4, record_5, record_6, record_7],
    ),
    (GetCoinRecords(wallet_id=uint32(0)), [record_1, record_2, record_3, record_4]),
    (GetCoinRecords(wallet_id=uint32(1)), [record_8, record_5]),
    (GetCoinRecords(wallet_id=uint32(2)), [record_9, record_6, record_7]),
]

get_coin_records_wallet_type_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(wallet_id=uint32(2), wallet_type=uint8(WalletType.STANDARD_WALLET)), [record_9, record_6]),
    (GetCoinRecords(wallet_type=uint8(WalletType.POOLING_WALLET)), [record_7]),
    (GetCoinRecords(wallet_type=uint8(WalletType.NFT)), []),
]

get_coin_records_coin_type_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(wallet_id=uint32(0), coin_type=uint8(CoinType.NORMAL)), [record_1, record_2, record_3, record_4]),
    (GetCoinRecords(wallet_id=uint32(0), coin_type=uint8(CoinType.CLAWBACK)), []),
    (GetCoinRecords(wallet_id=uint32(1), coin_type=uint8(CoinType.NORMAL)), [record_5]),
    (GetCoinRecords(wallet_id=uint32(1), coin_type=uint8(CoinType.CLAWBACK)), [record_8]),
    (GetCoinRecords(coin_type=uint8(CoinType.CLAWBACK)), [record_8, record_9]),
]

get_coin_records_coin_id_filter_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(coin_id_filter=HashFilter.include([])), []),
    (GetCoinRecords(coin_id_filter=HashFilter.include([coin_1.name(), coin_4.name()])), [record_1, record_4]),
    (GetCoinRecords(coin_id_filter=HashFilter.include([coin_1.name(), coin_4.puzzle_hash])), [record_1]),
    (GetCoinRecords(coin_id_filter=HashFilter.include([coin_9.name()])), [record_9]),
    (GetCoinRecords(wallet_id=uint32(0), coin_id_filter=HashFilter.include([coin_9.name()])), []),
    (
        GetCoinRecords(wallet_id=uint32(0), coin_id_filter=HashFilter.exclude([coin_9.name()])),
        [record_1, record_2, record_3, record_4],
    ),
]


get_coin_records_puzzle_hash_filter_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(puzzle_hash_filter=HashFilter.include([])), []),
    (
        GetCoinRecords(puzzle_hash_filter=HashFilter.include([coin_1.puzzle_hash, coin_4.puzzle_hash])),
        [record_1, record_4, record_6],
    ),
    (GetCoinRecords(puzzle_hash_filter=HashFilter.include([coin_1.puzzle_hash, coin_4.name()])), [record_1]),
    (GetCoinRecords(puzzle_hash_filter=HashFilter.include([coin_7.puzzle_hash])), [record_7]),
    (
        GetCoinRecords(
            wallet_type=uint8(WalletType.STANDARD_WALLET), puzzle_hash_filter=HashFilter.include([coin_7.puzzle_hash])
        ),
        [],
    ),
    (
        GetCoinRecords(
            wallet_type=uint8(WalletType.STANDARD_WALLET),
            puzzle_hash_filter=HashFilter.exclude([coin_7.puzzle_hash]),
        ),
        [record_8, record_9, record_1, record_2, record_3, record_4, record_5, record_6],
    ),
]

get_coin_records_parent_coin_id_filter_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(parent_coin_id_filter=HashFilter.include([])), []),
    (
        GetCoinRecords(parent_coin_id_filter=HashFilter.include([coin_5.name(), coin_4.parent_coin_info])),
        [record_9, record_4],
    ),
    (GetCoinRecords(parent_coin_id_filter=HashFilter.include([coin_1.parent_coin_info])), [record_1, record_2]),
    (GetCoinRecords(parent_coin_id_filter=HashFilter.include([coin_7.puzzle_hash])), []),
    (
        GetCoinRecords(
            coin_type=uint8(CoinType.CLAWBACK),
            parent_coin_id_filter=HashFilter.include([coin_5.name(), coin_4.parent_coin_info]),
        ),
        [record_9],
    ),
    (
        GetCoinRecords(
            coin_type=uint8(CoinType.CLAWBACK),
            parent_coin_id_filter=HashFilter.exclude([coin_5.name(), coin_4.parent_coin_info]),
        ),
        [record_8],
    ),
]

get_coin_records_amount_filter_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(amount_filter=AmountFilter.include([])), []),
    (
        GetCoinRecords(amount_filter=AmountFilter.include([uint64(12312)])),
        [record_1, record_3, record_4, record_5, record_6, record_7],
    ),
    (GetCoinRecords(amount_filter=AmountFilter.exclude([uint64(12312)])), [record_8, record_9, record_2]),
    (GetCoinRecords(amount_filter=AmountFilter.include([uint64(2), uint64(4)])), [record_8, record_9]),
    (
        GetCoinRecords(amount_filter=AmountFilter.include([uint64(12311), uint64(2), uint64(4)])),
        [record_8, record_9, record_2],
    ),
    (
        GetCoinRecords(
            coin_type=uint8(CoinType.CLAWBACK),
            amount_filter=AmountFilter.include([uint64(12311), uint64(2), uint64(4)]),
        ),
        [record_8, record_9],
    ),
    (
        GetCoinRecords(
            coin_type=uint8(CoinType.CLAWBACK),
            amount_filter=AmountFilter.exclude([uint64(12311), uint64(2), uint64(4)]),
        ),
        [],
    ),
]

get_coin_records_amount_range_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(amount_range=UInt64Range(start=uint64(1000000))), []),
    (GetCoinRecords(amount_range=UInt64Range(stop=uint64(0))), []),
    (
        GetCoinRecords(amount_range=UInt64Range(start=uint64(12312))),
        [record_1, record_3, record_4, record_5, record_6, record_7],
    ),
    (GetCoinRecords(amount_range=UInt64Range(stop=uint64(4))), [record_8, record_9]),
    (GetCoinRecords(amount_range=UInt64Range(start=uint64(2), stop=uint64(12311))), [record_8, record_9, record_2]),
    (GetCoinRecords(amount_range=UInt64Range(start=uint64(4), stop=uint64(12311))), [record_9, record_2]),
    (GetCoinRecords(amount_range=UInt64Range(start=uint64(5), stop=uint64(12311))), [record_2]),
]

get_coin_records_confirmed_range_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(confirmed_range=UInt32Range(start=uint32(20))), []),
    (GetCoinRecords(confirmed_range=UInt32Range(stop=uint32(0))), []),
    (GetCoinRecords(confirmed_range=UInt32Range(start=uint32(2), stop=uint32(1))), []),
    (
        GetCoinRecords(confirmed_range=UInt32Range(start=uint32(5))),
        [record_2, record_3, record_4, record_5, record_6, record_7],
    ),
    (GetCoinRecords(confirmed_range=UInt32Range(stop=uint32(2))), [record_8, record_9]),
    (GetCoinRecords(confirmed_range=UInt32Range(stop=uint32(4))), [record_8, record_9, record_1]),
    (GetCoinRecords(confirmed_range=UInt32Range(start=uint32(4), stop=uint32(4))), [record_1]),
    (
        GetCoinRecords(confirmed_range=UInt32Range(start=uint32(4), stop=uint32(5))),
        [record_1, record_2, record_3, record_4, record_5, record_6, record_7],
    ),
]

get_coin_records_spent_range_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (GetCoinRecords(spent_range=UInt32Range(start=uint32(20))), []),
    (GetCoinRecords(spent_range=UInt32Range(stop=uint32(0))), [record_8, record_1, record_2, record_5, record_7]),
    (GetCoinRecords(spent_range=UInt32Range(start=uint32(2), stop=uint32(1))), []),
    (GetCoinRecords(spent_range=UInt32Range(start=uint32(5), stop=uint32(10))), [record_3]),
    (GetCoinRecords(spent_range=UInt32Range(start=uint32(2), stop=uint32(10))), [record_9, record_3]),
    (GetCoinRecords(spent_range=UInt32Range(start=uint32(5), stop=uint32(15))), [record_3, record_4, record_6]),
]

get_coin_records_order_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (
        GetCoinRecords(wallet_id=uint32(0), order=uint8(CoinRecordOrder.spent_height)),
        [record_1, record_2, record_3, record_4],
    ),
    (GetCoinRecords(wallet_id=uint32(1), order=uint8(CoinRecordOrder.spent_height)), [record_5, record_8]),
    (
        GetCoinRecords(
            confirmed_range=UInt32Range(start=uint32(4), stop=uint32(5)), order=uint8(CoinRecordOrder.spent_height)
        ),
        [record_1, record_2, record_5, record_7, record_3, record_4, record_6],
    ),
]

get_coin_records_reverse_tests: List[Tuple[GetCoinRecords, List[WalletCoinRecord]]] = [
    (
        GetCoinRecords(wallet_id=uint32(0), order=uint8(CoinRecordOrder.spent_height), reverse=True),
        [record_4, record_3, record_1, record_2],
    ),
    (
        GetCoinRecords(wallet_id=uint32(1), order=uint8(CoinRecordOrder.spent_height), reverse=True),
        [record_5, record_8],
    ),
    (
        GetCoinRecords(confirmed_range=UInt32Range(start=uint32(1), stop=uint32(4)), reverse=True),
        [record_1, record_8, record_9],
    ),
    (
        GetCoinRecords(
            confirmed_range=UInt32Range(start=uint32(4), stop=uint32(5)),
            order=uint8(CoinRecordOrder.spent_height),
            reverse=True,
        ),
        [record_4, record_6, record_3, record_1, record_2, record_5, record_7],
    ),
]

get_coin_records_include_total_count_tests: List[Tuple[GetCoinRecords, int, List[WalletCoinRecord]]] = [
    (GetCoinRecords(wallet_id=uint32(0), include_total_count=True), 4, [record_1, record_2, record_3, record_4]),
    (
        GetCoinRecords(wallet_id=uint32(0), offset=uint32(1), limit=uint32(2), include_total_count=True),
        4,
        [record_2, record_3],
    ),
    (GetCoinRecords(wallet_id=uint32(1), include_total_count=True), 2, [record_8, record_5]),
    (GetCoinRecords(wallet_type=uint8(WalletType.NFT), include_total_count=True), 0, []),
    (GetCoinRecords(wallet_type=uint8(WalletType.POOLING_WALLET), include_total_count=True), 1, [record_7]),
]

get_coin_records_mixed_tests: List[Tuple[GetCoinRecords, int, List[WalletCoinRecord]]] = [
    (
        GetCoinRecords(
            offset=uint32(2),
            limit=uint32(2),
            coin_id_filter=HashFilter.include([coin_1.name(), coin_5.name(), coin_8.name(), coin_9.name()]),
            puzzle_hash_filter=HashFilter.exclude([coin_2.puzzle_hash]),
            parent_coin_id_filter=HashFilter.exclude([coin_7.parent_coin_info]),
            include_total_count=True,
        ),
        4,
        [record_1, record_5],
    ),
    (
        GetCoinRecords(
            offset=uint32(3),
            limit=uint32(4),
            wallet_type=uint8(WalletType.STANDARD_WALLET),
            coin_type=uint8(CoinType.NORMAL),
            puzzle_hash_filter=HashFilter.exclude([coin_2.puzzle_hash]),
            parent_coin_id_filter=HashFilter.exclude([coin_7.parent_coin_info]),
            include_total_count=True,
        ),
        5,
        [record_5, record_6],
    ),
    (
        GetCoinRecords(
            offset=uint32(1),
            limit=uint32(2),
            wallet_id=uint32(0),
            wallet_type=uint8(WalletType.STANDARD_WALLET),
            coin_type=uint8(CoinType.NORMAL),
            coin_id_filter=HashFilter.exclude([coin_1.puzzle_hash]),
            puzzle_hash_filter=HashFilter.include(
                [coin_1.puzzle_hash, coin_2.puzzle_hash, coin_3.puzzle_hash, coin_4.puzzle_hash]
            ),
            parent_coin_id_filter=HashFilter.exclude([coin_7.parent_coin_info]),
            amount_filter=AmountFilter.exclude([uint64(10)]),
            amount_range=UInt64Range(start=uint64(20), stop=uint64(200000)),
            confirmed_range=UInt32Range(start=uint32(2), stop=uint32(30)),
            spent_range=UInt32Range(start=uint32(1), stop=uint32(15)),
            order=uint8(CoinRecordOrder.spent_height),
            reverse=True,
            include_total_count=True,
        ),
        2,
        [record_3],
    ),
]


async def run_get_coin_records_test(
    request: GetCoinRecords, total_count: Optional[int], coin_records: List[WalletCoinRecord]
) -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        for record in [record_1, record_2, record_3, record_4, record_5, record_6, record_7, record_8, record_9]:
            await store.add_coin_record(record)

        result = await store.get_coin_records(
            offset=request.offset,
            limit=request.limit,
            wallet_id=request.wallet_id,
            wallet_type=None if request.wallet_type is None else WalletType(request.wallet_type),
            coin_type=None if request.coin_type is None else CoinType(request.coin_type),
            coin_id_filter=request.coin_id_filter,
            puzzle_hash_filter=request.puzzle_hash_filter,
            parent_coin_id_filter=request.parent_coin_id_filter,
            amount_filter=request.amount_filter,
            amount_range=request.amount_range,
            confirmed_range=request.confirmed_range,
            spent_range=request.spent_range,
            order=CoinRecordOrder(request.order),
            reverse=request.reverse,
            include_total_count=request.include_total_count,
        )

        assert result.records == coin_records
        assert result.coin_id_to_record == {coin.name(): coin for coin in coin_records}
        assert result.total_count == total_count


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_offset_limit_tests])
@pytest.mark.anyio
async def test_get_coin_records_offset_limit(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_wallet_id_tests])
@pytest.mark.anyio
async def test_get_coin_records_wallet_id(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_wallet_type_tests])
@pytest.mark.anyio
async def test_get_coin_records_wallet_type(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_coin_type_tests])
@pytest.mark.anyio
async def test_get_coin_records_coin_type(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_coin_id_filter_tests])
@pytest.mark.anyio
async def test_get_coin_records_coin_id_filter(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_puzzle_hash_filter_tests])
@pytest.mark.anyio
async def test_get_coin_records_puzzle_hash_filter(
    coins_request: GetCoinRecords, records: List[WalletCoinRecord]
) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_parent_coin_id_filter_tests])
@pytest.mark.anyio
async def test_get_coin_records_parent_coin_id_filter(
    coins_request: GetCoinRecords, records: List[WalletCoinRecord]
) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_amount_filter_tests])
@pytest.mark.anyio
async def test_get_coin_records_amount_filter(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_confirmed_range_tests])
@pytest.mark.anyio
async def test_get_coin_records_confirmed_range(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_spent_range_tests])
@pytest.mark.anyio
async def test_get_coin_records_spent_range(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_amount_range_tests])
@pytest.mark.anyio
async def test_get_coin_records_amount_range(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_order_tests])
@pytest.mark.anyio
async def test_get_coin_records_order(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, records", [*get_coin_records_reverse_tests])
@pytest.mark.anyio
async def test_get_coin_records_reverse(coins_request: GetCoinRecords, records: List[WalletCoinRecord]) -> None:
    await run_get_coin_records_test(coins_request, None, records)


@pytest.mark.parametrize("coins_request, total_count, records", [*get_coin_records_include_total_count_tests])
@pytest.mark.anyio
async def test_get_coin_records_total_count(
    coins_request: GetCoinRecords, total_count: int, records: List[WalletCoinRecord]
) -> None:
    await run_get_coin_records_test(coins_request, total_count, records)


@pytest.mark.parametrize("coins_request, total_count, records", [*get_coin_records_mixed_tests])
@pytest.mark.anyio
async def test_get_coin_records_mixed(
    coins_request: GetCoinRecords, total_count: int, records: List[WalletCoinRecord]
) -> None:
    await run_get_coin_records_test(coins_request, total_count, records)


@pytest.mark.anyio
async def test_get_coin_records_total_count_cache() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        for record in [record_1, record_2, record_3]:
            await store.add_coin_record(record)

        # Make sure the total count increases for the same query when adding more records
        assert (await store.get_coin_records(include_total_count=True)).total_count == 3
        await store.add_coin_record(record_4)
        assert (await store.get_coin_records(include_total_count=True)).total_count == 4
        # Make sure the total count increases for the same query when changing spent state
        assert (
            await store.get_coin_records(spent_range=UInt32Range(start=uint32(10)), include_total_count=True)
        ).total_count == 2
        await store.set_spent(record_1.name(), 10)
        assert (
            await store.get_coin_records(spent_range=UInt32Range(start=uint32(10)), include_total_count=True)
        ).total_count == 3
        # Make sure the total count increases for the same query when deleting a coin record
        assert (await store.get_coin_records(include_total_count=True)).total_count == 4
        await store.delete_coin_record(record_4.name())
        assert (await store.get_coin_records(include_total_count=True)).total_count == 3
        # Make sure the total count increases for the same query when rolling back
        assert (await store.get_coin_records(include_total_count=True)).total_count == 3
        await store.rollback_to_block(0),
        assert (await store.get_coin_records(include_total_count=True)).total_count == 0


@pytest.mark.anyio
async def test_get_coin_records_total_count_cache_reset() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        for record in [record_1, record_2, record_3, record_8, record_9]:
            await store.add_coin_record(record)

        def assert_result(result: GetCoinRecordsResult, *, expected_total_count: int, expected_cache_size: int) -> None:
            assert result.total_count == expected_total_count
            assert len(store.total_count_cache.cache) == expected_cache_size

        async def test_cache() -> None:
            # Try each request a few times and make sure the cache count states the same for each time but increases
            # with every new request.
            for _ in range(5):
                result = await store.get_coin_records(
                    coin_id_filter=HashFilter.include([record_1.name()]), include_total_count=True
                )
                assert_result(result, expected_total_count=1, expected_cache_size=1)
            for _ in range(5):
                result = await store.get_coin_records(coin_type=CoinType.CLAWBACK, include_total_count=True)
                assert_result(result, expected_total_count=2, expected_cache_size=2)
            for _ in range(5):
                result = await store.get_coin_records(
                    coin_id_filter=HashFilter.include([record_2.name()]), include_total_count=True
                )
                assert_result(result, expected_total_count=1, expected_cache_size=3)
            for _ in range(5):
                result = await store.get_coin_records(
                    coin_id_filter=HashFilter.include([record_1.name(), record_2.name()]), include_total_count=True
                )
                assert_result(result, expected_total_count=2, expected_cache_size=4)

        # All the actions in here should reset the cache and lead to the same results again in `test_cache`.
        for trigger in [
            store.add_coin_record(record_4),
            store.set_spent(coin_4.name(), 10),
            store.delete_coin_record(record_4.name()),
            store.rollback_to_block(1000),
            store.delete_wallet(uint32(record_1.wallet_id)),
        ]:
            await test_cache()
            await trigger


def record(c: Coin, *, confirmed: int, spent: int) -> WalletCoinRecord:
    return WalletCoinRecord(c, uint32(confirmed), uint32(spent), spent != 0, False, WalletType.STANDARD_WALLET, 0)


@pytest.mark.anyio
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


@pytest.mark.anyio
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

        assert (
            await store.get_coin_records(
                coin_id_filter=HashFilter.include(
                    [
                        coin_1.name(),
                        coin_2.name(),
                        coin_3.name(),
                        coin_4.name(),
                        coin_5.name(),
                    ]
                )
            )
        ).records == [
            r1,
            r2,
            r3,
            r4,
            r5,
        ]

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


@pytest.mark.anyio
async def test_count_small_unspent(seeded_random: random.Random) -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        coin_1 = Coin(bytes32.random(seeded_random), bytes32.random(seeded_random), uint64(1))
        coin_2 = Coin(bytes32.random(seeded_random), bytes32.random(seeded_random), uint64(2))
        coin_3 = Coin(bytes32.random(seeded_random), bytes32.random(seeded_random), uint64(4))

        r1 = record(coin_1, confirmed=1, spent=0)
        r2 = record(coin_2, confirmed=2, spent=0)
        r3 = record(coin_3, confirmed=3, spent=0)

        await store.add_coin_record(r1)
        await store.add_coin_record(r2)
        await store.add_coin_record(r3)
        await store.add_coin_record(record_8)

        assert await store.count_small_unspent(5) == 3
        assert await store.count_small_unspent(4) == 2
        assert await store.count_small_unspent(3) == 2
        assert await store.count_small_unspent(2) == 1
        assert await store.count_small_unspent(1) == 0
        assert await store.count_small_unspent(3, coin_type=CoinType.CLAWBACK) == 1

        await store.set_spent(coin_2.name(), uint32(12))
        await store.set_spent(coin_8.name(), uint32(12))

        assert await store.count_small_unspent(5) == 2
        assert await store.count_small_unspent(4) == 1
        assert await store.count_small_unspent(3) == 1
        assert await store.count_small_unspent(2) == 1
        assert await store.count_small_unspent(3, coin_type=CoinType.CLAWBACK) == 0
        assert await store.count_small_unspent(1) == 0


@pytest.mark.anyio
async def test_get_coin_records_between() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletCoinStore.create(db_wrapper)

        assert await store.get_all_unspent_coins() == set()

        await store.add_coin_record(record_1)  # not spent
        await store.add_coin_record(record_2)  # not spent
        await store.add_coin_record(record_5)  # spent
        await store.add_coin_record(record_8)  # spent

        records = await store.get_coin_records_between(1, 0, 0)
        assert len(records) == 0
        records = await store.get_coin_records_between(1, 0, 3)
        assert len(records) == 1
        assert records[0] == record_5
        records = await store.get_coin_records_between(1, 0, 4, coin_type=CoinType.CLAWBACK)
        assert len(records) == 1
        assert records[0] == record_8


@pytest.mark.anyio
async def test_delete_wallet(seeded_random: random.Random) -> None:
    dummy_records = DummyWalletCoinRecords(seeded_random=seeded_random)
    for i in range(5):
        dummy_records.generate(i, i * 5)
    async with DBConnection(1) as wrapper:
        store = await WalletCoinStore.create(wrapper)
        # Add the records per wallet and verify them
        for wallet_id, records in dummy_records.records_per_wallet.items():
            for coin_record in records:
                await store.add_coin_record(coin_record)
            assert set((await store.get_coin_records(wallet_id=wallet_id)).records) == set(records)
        # Remove one wallet after the other and verify before and after each
        for wallet_id, records in dummy_records.records_per_wallet.items():
            # Assert the existence again here to make sure the previous removals did not affect other wallet_ids
            assert set((await store.get_coin_records(wallet_id=wallet_id)).records) == set(records)
            # Remove the wallet_id and make sure its removed fully
            await store.delete_wallet(wallet_id)
            assert (await store.get_coin_records(wallet_id=wallet_id)).records == []
