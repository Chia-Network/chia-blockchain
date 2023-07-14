from __future__ import annotations

import time
from secrets import token_bytes

import pytest

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.trading.trade_store import TradeStore, migrate_coin_of_interest
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_coin_store import WalletCoinStore
from tests.util.db_connection import DBConnection

coin_1 = Coin(token_bytes(32), token_bytes(32), uint64(12311))
coin_2 = Coin(coin_1.parent_coin_info, token_bytes(32), uint64(12312))
coin_3 = Coin(coin_1.parent_coin_info, token_bytes(32), uint64(12313))
record_1 = WalletCoinRecord(coin_1, uint32(4), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
record_2 = WalletCoinRecord(coin_2, uint32(5), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)
record_3 = WalletCoinRecord(coin_3, uint32(6), uint32(0), False, True, WalletType.STANDARD_WALLET, 0)


@pytest.mark.asyncio
async def test_get_coins_of_interest_with_trade_statuses() -> None:
    async with DBConnection(1) as db_wrapper:
        coin_store = await WalletCoinStore.create(db_wrapper)
        trade_store = await TradeStore.create(db_wrapper)
        await coin_store.add_coin_record(record_1)
        await coin_store.add_coin_record(record_2)
        await coin_store.add_coin_record(record_3)

        tr1_name: bytes32 = bytes32(token_bytes(32))
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
        )
        await trade_store.add_trade_record(tr1, offer_name=bytes32(token_bytes(32)))

        tr2_name: bytes32 = bytes32(token_bytes(32))
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
        )
        await trade_store.add_trade_record(tr2, offer_name=bytes32(token_bytes(32)))

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
        )
        await trade_store.add_trade_record(tr2_1, offer_name=bytes32(token_bytes(32)))

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
