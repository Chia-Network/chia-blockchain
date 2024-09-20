from __future__ import annotations

import random
import time

import pytest
from chia_rs import G2Element

from chia._tests.util.db_connection import DBConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.conditions import ConditionValidTimes
from chia.wallet.trade_record import TradeRecord, TradeRecordOld
from chia.wallet.trading.offer import Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.trading.trade_store import TradeStore, migrate_coin_of_interest
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import WalletCoinStore
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

module_seeded_random = random.Random()
module_seeded_random.seed(a=0, version=2)

coin_1 = Coin(bytes32.random(module_seeded_random), bytes32.random(module_seeded_random), uint64(12311))
coin_2 = Coin(coin_1.parent_coin_info, bytes32.random(module_seeded_random), uint64(12312))
coin_3 = Coin(coin_1.parent_coin_info, bytes32.random(module_seeded_random), uint64(12313))
record_1 = WalletCoinRecord(coin_1, uint32(4), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
record_2 = WalletCoinRecord(coin_2, uint32(5), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
record_3 = WalletCoinRecord(coin_3, uint32(6), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)


@pytest.mark.anyio
async def test_get_coins_of_interest_with_trade_statuses(seeded_random: random.Random) -> None:
    async with DBConnection(1) as db_wrapper:
        coin_store = await WalletCoinStore.create(db_wrapper)
        trade_store = await TradeStore.create(db_wrapper)
        await coin_store.add_coin_record(record_1)
        await coin_store.add_coin_record(record_2)
        await coin_store.add_coin_record(record_3)

        tr1_name: bytes32 = bytes32.random(seeded_random)
        tr1 = TradeRecord(
            confirmed_at_index=uint32(0),
            accepted_at_time=None,
            created_at_time=uint64(time.time()),
            is_my_offer=True,
            sent=uint32(0),
            offer=bytes([1, 2, 3]),
            taken_offer=None,
            coins_of_interest=[coin_2],
            trade_id=tr1_name,
            status=uint32(TradeStatus.PENDING_ACCEPT.value),
            sent_to=[],
            valid_times=ConditionValidTimes(),
        )
        await trade_store.add_trade_record(tr1, offer_name=bytes32.random(seeded_random))

        tr2_name: bytes32 = bytes32.random(seeded_random)
        tr2 = TradeRecord(
            confirmed_at_index=uint32(0),
            accepted_at_time=None,
            created_at_time=uint64(time.time()),
            is_my_offer=True,
            sent=uint32(0),
            offer=bytes([1, 2, 3]),
            taken_offer=None,
            coins_of_interest=[coin_1, coin_3],
            trade_id=tr2_name,
            status=uint32(TradeStatus.PENDING_CONFIRM.value),
            sent_to=[],
            valid_times=ConditionValidTimes(),
        )
        await trade_store.add_trade_record(tr2, offer_name=bytes32.random(seeded_random))

        assert await trade_store.get_coin_ids_of_interest_with_trade_statuses([TradeStatus.PENDING_CONFIRM]) == {
            coin_1.name(),
            coin_3.name(),
        }
        assert await trade_store.get_coin_ids_of_interest_with_trade_statuses([TradeStatus.PENDING_ACCEPT]) == {
            coin_2.name()
        }

        # test replace trade record
        tr2_1 = TradeRecord(
            confirmed_at_index=uint32(0),
            accepted_at_time=None,
            created_at_time=uint64(time.time()),
            is_my_offer=True,
            sent=uint32(0),
            offer=bytes([1, 2, 3]),
            taken_offer=None,
            coins_of_interest=[coin_2],
            trade_id=tr2_name,
            status=uint32(TradeStatus.PENDING_CONFIRM.value),
            sent_to=[],
            valid_times=ConditionValidTimes(),
        )
        await trade_store.add_trade_record(tr2_1, offer_name=bytes32.random(seeded_random))

        assert await trade_store.get_coin_ids_of_interest_with_trade_statuses([TradeStatus.PENDING_CONFIRM]) == {
            coin_2.name()
        }

        # test migration
        async with trade_store.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("DELETE FROM coin_of_interest_to_trade_record")

        assert await trade_store.get_coin_ids_of_interest_with_trade_statuses([TradeStatus.PENDING_ACCEPT]) == set()

        async with trade_store.db_wrapper.writer_maybe_transaction() as conn:
            await migrate_coin_of_interest(trade_store.log, conn)

        assert await trade_store.get_coin_ids_of_interest_with_trade_statuses([TradeStatus.PENDING_ACCEPT]) == {
            coin_2.name()
        }


@pytest.mark.anyio
async def test_valid_times_migration() -> None:
    async with DBConnection(1) as db_wrapper:
        async with db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS trade_records("
                " trade_record blob,"
                " trade_id text PRIMARY KEY,"
                " status int,"
                " confirmed_at_index int,"
                " created_at_time bigint,"
                " sent int,"
                " is_my_offer tinyint)"
            )

        fake_offer = Offer({}, WalletSpendBundle([], G2Element()), {})
        fake_coin = Coin(bytes32([0] * 32), bytes32([0] * 32), uint64(0))
        old_record = TradeRecordOld(
            confirmed_at_index=uint32(0),
            accepted_at_time=None,
            created_at_time=uint64(1000000),
            is_my_offer=True,
            sent=uint32(0),
            offer=bytes(fake_offer),
            taken_offer=None,
            coins_of_interest=[fake_coin],
            trade_id=bytes32([0] * 32),
            status=uint32(TradeStatus.PENDING_ACCEPT.value),
            sent_to=[],
        )

        async with db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT INTO trade_records "
                "(trade_record, trade_id, status, confirmed_at_index, created_at_time, sent, is_my_offer) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    bytes(old_record),
                    old_record.trade_id.hex(),
                    old_record.status,
                    old_record.confirmed_at_index,
                    old_record.created_at_time,
                    old_record.sent,
                    old_record.is_my_offer,
                ),
            )
            await cursor.close()

        trade_store = await TradeStore.create(db_wrapper)
        rec = await trade_store.get_trade_record(old_record.trade_id)
        assert rec is not None
        assert rec.valid_times == ConditionValidTimes()


@pytest.mark.anyio
async def test_large_trade_record_query() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await TradeStore.create(db_wrapper)
        trade_records_to_insert = []
        for _ in range(db_wrapper.host_parameter_limit + 1):
            offer_name = bytes32.random()
            trade_record_old = TradeRecordOld(
                confirmed_at_index=uint32(0),
                accepted_at_time=None,
                created_at_time=uint64(1000000),
                is_my_offer=True,
                sent=uint32(0),
                offer=b"",
                taken_offer=None,
                coins_of_interest=[],
                trade_id=offer_name,
                status=uint32(TradeStatus.PENDING_ACCEPT.value),
                sent_to=[],
            )
            trade_records_to_insert.append(
                (
                    bytes(trade_record_old),
                    trade_record_old.trade_id.hex(),
                    trade_record_old.status,
                    trade_record_old.confirmed_at_index,
                    trade_record_old.created_at_time,
                    trade_record_old.sent,
                    trade_record_old.trade_id,
                    trade_record_old.is_my_offer,
                )
            )
        async with db_wrapper.writer_maybe_transaction() as conn:
            await conn.executemany("INSERT INTO trade_records VALUES(?, ?, ?, ?, ?, ?, ?, ?)", trade_records_to_insert)
            # Insert a specific trade_record_times item for the last trade_records item
            await conn.execute(
                "INSERT INTO trade_record_times VALUES(?, ?)",
                (offer_name, bytes(ConditionValidTimes(min_height=uint32(42)))),
            )
        all_trades = await store.get_all_trades()
        assert len(all_trades) == db_wrapper.host_parameter_limit + 1
        # Check that all trade_record items have correct valid_times
        empty = ConditionValidTimes()
        assert all(trade.valid_times == empty for trade in all_trades[:-1])
        assert all_trades[-1].valid_times.min_height == uint32(42)
