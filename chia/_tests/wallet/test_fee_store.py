from __future__ import annotations

import dataclasses

import pytest
from tests.util.db_connection import DBConnection

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from chia.wallet.fee_record import FeePerCost, FeeRecord, FeeRecordKey
from chia.wallet.wallet_fee_store import FeeStore

FPC_ZERO = FeePerCost(uint64(0), uint64(1))
FPC_ONE = FeePerCost(uint64(1), uint64(1))
FPC_FIVE = FeePerCost(uint64(5), uint64(1))


def create_default_record() -> FeeRecord:
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


block_hash1 = b"\0" * 32
key1 = FeeRecordKey(bytes32(block_hash1), "", uint8(0))
fee_record_1 = create_default_record()
replacing_record = dataclasses.replace(fee_record_1, block_fpc=FPC_ZERO)


async def test_create_fee_store(db_version: int) -> None:
    async with DBConnection(db_version) as db_wrapper:
        await FeeStore.create(db_wrapper)


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

        # test adding duplicates when not allowed
        await store.add_fee_record(key1, replacing_record)  # Implicit replace=False
        assert (await store.get_fee_record(key1)) == fee_record_1
        await store.add_fee_record(key1, replacing_record, replace=False)
        assert (await store.get_fee_record(key1)) == fee_record_1

        # test adding duplicates when allowed to overwrite
        await store.add_fee_record(key1, replacing_record, replace=True)
        assert (await store.get_fee_record(key1)) == replacing_record
