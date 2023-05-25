from __future__ import annotations

import time
from secrets import token_bytes
from typing import Any, Dict, Optional

import pytest

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.singleton import create_singleton_puzzle
from chia.wallet.singleton_coin_record import SingletonCoinRecord
from chia.wallet.wallet_singleton_store import WalletSingletonStore
from tests.util.db_connection import DBConnection

fake_singleton_id = bytes32(b"N" * 32)


def get_new_singleton_record(custom_data: Optional[Dict[str, Any]] = None) -> SingletonCoinRecord:
    singleton_id: bytes32 = bytes32(token_bytes(32))
    inner_puz: Program = Program.to(1)
    parent_puz: Program = create_singleton_puzzle(inner_puz, singleton_id)
    parent_puz_hash: bytes32 = parent_puz.get_tree_hash()
    parent_coin: Coin = Coin(singleton_id, parent_puz_hash, uint64(1))
    lineage_proof: LineageProof = LineageProof(singleton_id, inner_puz.get_tree_hash(), uint64(1))
    child_coin: Coin = Coin(parent_coin.name(), parent_puz.get_tree_hash(), uint64(1))
    if not custom_data:
        custom_data = {"custom_field": b"value", "custom_field_2": 202}
    record = SingletonCoinRecord(
        coin=child_coin,
        singleton_id=singleton_id,
        wallet_id=uint32(2),
        inner_puzzle=inner_puz,
        inner_puzzle_hash=inner_puz.get_tree_hash(),
        confirmed=False,
        confirmed_at_height=uint32(0),
        spent_height=uint32(0),
        lineage_proof=lineage_proof,
        custom_data=custom_data,
        generation=uint32(0),
        timestamp=uint64(time.time()),
    )
    return record


def get_next_singleton_record(record: SingletonCoinRecord) -> SingletonCoinRecord:
    inner_puz: Program = Program.to(1)
    parent_puz: Program = create_singleton_puzzle(inner_puz, record.singleton_id)
    next_lineage_proof: LineageProof = LineageProof(record.coin.parent_coin_info, inner_puz.get_tree_hash(), uint64(1))
    child_coin: Coin = Coin(record.coin.name(), parent_puz.get_tree_hash(), uint64(1))
    next_record = SingletonCoinRecord(
        coin=child_coin,
        singleton_id=record.singleton_id,
        wallet_id=record.wallet_id,
        inner_puzzle=inner_puz,
        inner_puzzle_hash=inner_puz.get_tree_hash(),
        confirmed=False,
        confirmed_at_height=uint32(0),
        spent_height=uint32(0),
        lineage_proof=next_lineage_proof,
        custom_data=record.custom_data,
        generation=uint32(record.generation + 1),
        timestamp=uint64(time.time()),
    )
    return next_record


@pytest.mark.asyncio
async def test_singleton_store() -> None:
    async with DBConnection(1) as wrapper:
        db = await WalletSingletonStore.create(wrapper)
        record = get_new_singleton_record()
        singleton_id = record.singleton_id
        # add record to DB
        await db.add_singleton_record(record)

        # fetch record by coin_id
        rec = await db.get_record_by_coin_id(record.name())
        assert rec == record

        # fetch non-existent coin
        rec = await db.get_record_by_coin_id(bytes32(token_bytes(32)))
        assert rec is None

        # make record confirmed
        confirmed_height = uint32(10)
        timestamp = uint64(time.time())
        await db.set_confirmed(record.name(), confirmed_height, timestamp)
        rec = await db.get_record_by_coin_id(record.name())
        assert isinstance(rec, SingletonCoinRecord)
        assert rec.confirmed
        assert rec.confirmed_at_height == confirmed_height

        # get the next singleton record and add it to DB
        next_record = get_next_singleton_record(record)
        await db.add_singleton_record(next_record)

        # check the new record exists and the old record has been set to spent
        recs = await db.get_records_by_singleton_id(record.singleton_id)
        assert len(recs) == 2
        assert not recs[0].confirmed
        assert recs[1].confirmed
        assert recs[0].generation == 1
        assert recs[1].spent_height == 0

        # check get_latest_singleton with and without filtering confirmed
        latest = await db.get_latest_singleton(singleton_id)
        assert latest == recs[0]
        latest = await db.get_latest_singleton(singleton_id, only_confirmed=True)
        assert latest == recs[1]

        # check get_unconfirmed_singletons
        unconfirmed = await db.get_unconfirmed_singletons(singleton_id)
        assert len(unconfirmed) == 1
        assert unconfirmed[0] == recs[0]

        # confirm the new record
        await db.set_confirmed(next_record.name(), uint32(20), uint64(time.time()))
        recs = await db.get_records_by_singleton_id(record.singleton_id)
        assert recs[0].confirmed
        assert recs[1].spent_height == recs[0].confirmed_at_height == uint32(20)

        # Delete the last record
        await db.delete_record_by_coin_id(next_record.name())
        recs = await db.get_records_by_singleton_id(singleton_id)
        assert len(recs) == 1
        assert recs[0].name() == record.name()

        # Delete all records by id
        await db.delete_records_by_singleton_id(singleton_id)
        recs = await db.get_records_by_singleton_id(singleton_id)
        assert len(recs) == 0


@pytest.mark.asyncio
async def test_get_records_by_singleton_id() -> None:
    async with DBConnection(1) as wrapper:
        db = await WalletSingletonStore.create(wrapper)
        one = uint32(1)

        recs = await db.get_records_by_singleton_id(fake_singleton_id)
        assert recs == []
        record = get_new_singleton_record()
        recs = await db.get_records_by_singleton_id(record.singleton_id)
        assert len(recs) == 0
        recs = await db.get_records_by_singleton_id(record.singleton_id, one, one, one)
        assert len(recs) == 0
        await db.add_singleton_record(record)
        recs = await db.get_records_by_singleton_id(record.singleton_id)
        assert len(recs) == 1
        recs = await db.get_records_by_singleton_id(record.singleton_id, one, one, one)
        assert len(recs) == 0
        recs = await db.get_records_by_singleton_id(record.singleton_id, one, uint32(20), one)


@pytest.mark.asyncio
async def test_get_record_by_coin_id() -> None:
    async with DBConnection(1) as wrapper:
        db = await WalletSingletonStore.create(wrapper)

        rec = await db.get_record_by_coin_id(fake_singleton_id)
        assert rec is None

        # add record to DB
        record = get_new_singleton_record()
        await db.add_singleton_record(record)

        # fetch record by coin_id
        rec = await db.get_record_by_coin_id(record.name())
        assert rec == record


@pytest.mark.asyncio
async def test_get_latest_singleton() -> None:
    async with DBConnection(1) as wrapper:
        db = await WalletSingletonStore.create(wrapper)
        record_1 = get_new_singleton_record()
        await db.add_singleton_record(record_1)
        record_2 = get_new_singleton_record()
        await db.add_singleton_record(record_2)

        # Test we can get record 1
        latest = await db.get_latest_singleton(record_1.singleton_id)
        assert latest == record_1
        # Test we get nothing if requesting only_confirmed
        latest = await db.get_latest_singleton(record_1.singleton_id, only_confirmed=True)
        assert latest is None

        # confirm record 1 and check it is returned in only_confirmed
        await db.set_confirmed(record_1.name(), uint32(10), uint64(time.time()))
        latest = await db.get_latest_singleton(record_1.singleton_id, only_confirmed=True)
        assert isinstance(latest, SingletonCoinRecord)
        assert latest.singleton_id == record_1.singleton_id


@pytest.mark.asyncio
async def test_set_spent() -> None:
    async with DBConnection(1) as wrapper:
        db = await WalletSingletonStore.create(wrapper)
        record_1 = get_new_singleton_record()
        await db.add_singleton_record(record_1)
        # Don't add the second record
        record_2 = get_new_singleton_record()

        # set record_1 confirmed and spent
        await db.set_confirmed(record_1.name(), uint32(10), uint64(time.time()))
        latest = await db.get_latest_singleton(record_1.singleton_id, only_confirmed=True)
        assert isinstance(latest, SingletonCoinRecord)
        await db.set_spent(latest.name(), uint32(20), uint64(time.time()))
        last_record = await db.get_record_by_coin_id(latest.name())
        assert isinstance(last_record, SingletonCoinRecord)
        assert last_record.spent_height == uint32(20)

        # Try to set spent for non-existing record
        await db.set_spent(record_2.name(), uint32(20), uint64(time.time()))
        res = await db.get_record_by_coin_id(record_2.name())
        assert res is None


@pytest.mark.asyncio
async def test_set_confirmed() -> None:
    async with DBConnection(1) as wrapper:
        db = await WalletSingletonStore.create(wrapper)
        record_1 = get_new_singleton_record()
        await db.add_singleton_record(record_1)
        # Don't add the second record
        record_2 = get_new_singleton_record()

        # set record_1 confirmed (it has no parent)
        await db.set_confirmed(record_1.name(), uint32(10), uint64(time.time()))
        res = await db.get_record_by_coin_id(record_1.coin.parent_coin_info)  # this is probably redundant
        assert res is None

        latest = await db.get_latest_singleton(record_1.singleton_id)
        assert isinstance(latest, SingletonCoinRecord)
        assert latest.confirmed

        # set confirmed for non-existent record_2
        await db.set_confirmed(record_2.name(), uint32(10), uint64(time.time()))
        res = await db.get_record_by_coin_id(record_2.name())
        assert res is None

        # add record_2 and set confirmed
        await db.add_singleton_record(record_2)
        await db.set_confirmed(record_2.name(), uint32(20), uint64(time.time()))

        # get next record and add it
        next_record_2 = get_next_singleton_record(record_2)
        await db.add_singleton_record(next_record_2)
        await db.set_confirmed(next_record_2.name(), uint32(30), uint64(time.time()))

        # check parent has been set to spent
        parent_record = await db.get_record_by_coin_id(record_2.name())
        assert isinstance(parent_record, SingletonCoinRecord)
        assert parent_record.spent_height == uint32(30)


@pytest.mark.asyncio
async def test_custom_data() -> None:
    async with DBConnection(1, foreign_keys=True) as wrapper:
        db = await WalletSingletonStore.create(wrapper)
        custom_data = {"field_1": 100, "field_2": b"some text"}
        record = get_new_singleton_record(custom_data)
        await db.add_singleton_record(record)
        res = await db.get_records_by_singleton_id(record.singleton_id)
        assert res[0].custom_data == custom_data

        # delete the singleton and check it's removed from custom data table
        await db.delete_records_by_singleton_id(record.singleton_id)
        custom_res = await db.get_custom_data_by_coin_id(record.name())
        assert custom_res is None
