from __future__ import annotations

import dataclasses

import pytest

from chia._tests.util.db_connection import DBConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from chia.wallet.fee_record import FeePerCost, FeeRecord, FeeRecordKey
from chia.wallet.wallet_fee_store import FeeStore

FPC_ZERO = FeePerCost(uint64(0), uint64(1))
FPC_ONE = FeePerCost(uint64(1), uint64(1))
FPC_TWO = FeePerCost(uint64(2), uint64(1))
FPC_FIVE = FeePerCost(uint64(5), uint64(1))


def create_default_fee_record() -> FeeRecord:
    return FeeRecord(
        block_index=uint32(1),
        block_time=uint64(0),
        block_fpc=FPC_ZERO,
        estimated_fpc=FPC_ZERO,
        fee_to_add_std_tx=uint64(0),
        current_mempool_cost=uint64(0),
        current_mempool_fees=uint64(0),
        minimum_fee_per_cost_to_replace=FPC_ZERO,
    )


fee_record_2 = FeeRecord(
    block_index=uint32(2),
    block_time=uint64(2),
    block_fpc=FPC_TWO,
    estimated_fpc=FPC_TWO,
    fee_to_add_std_tx=uint64(2),
    current_mempool_cost=uint64(2),
    current_mempool_fees=uint64(2),
    minimum_fee_per_cost_to_replace=FPC_TWO,
)


block_hash_1 = b"\0" * 32
key1 = FeeRecordKey(bytes32(block_hash_1), "", uint8(0))
fee_record_1 = create_default_fee_record()
replacing_record = dataclasses.replace(fee_record_1, block_fpc=FPC_ZERO)
block_hash_2 = b"2" * 32
key2 = FeeRecordKey(bytes32(block_hash_2), "2", uint8(2))


@pytest.mark.anyio
async def test_create_fee_store(db_version: int) -> None:
    async with DBConnection(db_version) as db_wrapper:
        await FeeStore.create(db_wrapper)


@pytest.mark.anyio
async def test_create_fee_store_already_existing(db_version: int) -> None:
    async with DBConnection(db_version) as db_wrapper:
        fs1 = await FeeStore.create(db_wrapper)
        await fs1.add_fee_record(key1, fee_record_1)
        fs2 = await FeeStore.create(db_wrapper)
        assert (await fs2.get_fee_record(key1)) == fee_record_1
    # with pytest.raises(ValueError, match=error):


@pytest.mark.anyio
async def test_add_fee_record() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await FeeStore.create(db_wrapper)

        assert (await store.get_fee_record(key1)) is None
        await store.add_fee_record(key1, fee_record_1)

        # test adding duplicates when not allowed. Implicit replace=False
        with pytest.raises(ValueError):
            await store.add_fee_record(key1, replacing_record)
            assert (await store.get_fee_record(key1)) == fee_record_1

        # test adding duplicates when not allowed - explicit replace=False
        with pytest.raises(ValueError):
            await store.add_fee_record(key1, replacing_record, replace=False)
            assert (await store.get_fee_record(key1)) == fee_record_1

        # test adding duplicates when allowed to overwrite
        await store.add_fee_record(key1, replacing_record, replace=True)
        assert (await store.get_fee_record(key1)) == replacing_record


@pytest.mark.anyio
async def test_row_to_fee_record() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await FeeStore.create(db_wrapper)
        await store.add_fee_record(key1, fee_record_1)
        stored_and_converted = await store.get_fee_record(key1)
        assert stored_and_converted == fee_record_1


@pytest.mark.anyio
async def test_values_are_preserved() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await FeeStore.create(db_wrapper)

        assert (await store.get_fee_record(key1)) is None
        await store.add_fee_record(key2, fee_record_2)

        # retrieve, compare
        value_check = await store.get_fee_record(key2)
        assert value_check == fee_record_2
