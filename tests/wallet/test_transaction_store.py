from __future__ import annotations

import dataclasses
from secrets import token_bytes
from typing import Any, List

import pytest

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.util.ints import uint8, uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.wallet_transaction_store import WalletTransactionStore, filter_ok_mempool_status
from tests.util.db_connection import DBConnection

coin_1 = Coin(token_bytes(32), token_bytes(32), uint64(12312))
coin_2 = Coin(token_bytes(32), token_bytes(32), uint64(1234))
coin_3 = Coin(token_bytes(32), token_bytes(32), uint64(12312 - 1234))

tr1 = TransactionRecord(
    uint32(0),  # confirmed height
    uint64(1000),  # created_at_time
    bytes32(token_bytes(32)),  # to_puzzle_hash
    uint64(1234),  # amount
    uint64(12),  # fee_amount
    False,  # confirmed
    uint32(0),  # sent
    None,  # Optional[SpendBundle] spend_bundle
    [coin_2, coin_3],  # additions
    [coin_1],  # removals
    uint32(1),  # wallet_id
    [],  # List[Tuple[str, uint8, Optional[str]]] sent_to
    bytes32(token_bytes(32)),  # trade_id
    uint32(TransactionType.OUTGOING_TX),  # type
    bytes32(token_bytes(32)),  # name
    [],  # List[Tuple[bytes32, List[bytes]]] memos
)


@pytest.mark.asyncio
async def test_add() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        assert await store.get_transaction_record(tr1.name) is None
        await store.add_transaction_record(tr1)
        assert await store.get_transaction_record(tr1.name) == tr1


@pytest.mark.asyncio
async def test_delete() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        await store.add_transaction_record(tr1)
        assert await store.get_transaction_record(tr1.name) == tr1
        await store.delete_transaction_record(tr1.name)
        assert await store.get_transaction_record(tr1.name) is None


@pytest.mark.asyncio
async def test_set_confirmed() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        await store.add_transaction_record(tr1)
        await store.set_confirmed(tr1.name, uint32(100))

        assert await store.get_transaction_record(tr1.name) == dataclasses.replace(
            tr1, confirmed=True, confirmed_at_height=uint32(100)
        )


@pytest.mark.asyncio
async def test_increment_sent_noop() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        assert (
            await store.increment_sent(bytes32(token_bytes(32)), "peer1", MempoolInclusionStatus.PENDING, None) is False
        )


@pytest.mark.asyncio
async def test_increment_sent() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        await store.add_transaction_record(tr1)
        tr = await store.get_transaction_record(tr1.name)
        assert tr.sent == 0
        assert tr.sent_to == []

        assert await store.increment_sent(tr1.name, "peer1", MempoolInclusionStatus.PENDING, None) is True
        tr = await store.get_transaction_record(tr1.name)
        assert tr.sent == 1
        assert tr.sent_to == [("peer1", uint8(2), None)]

        assert await store.increment_sent(tr1.name, "peer1", MempoolInclusionStatus.SUCCESS, None) is True
        tr = await store.get_transaction_record(tr1.name)
        assert tr.sent == 1
        assert tr.sent_to == [("peer1", uint8(2), None), ("peer1", uint8(1), None)]

        assert await store.increment_sent(tr1.name, "peer2", MempoolInclusionStatus.SUCCESS, None) is True
        tr = await store.get_transaction_record(tr1.name)
        assert tr.sent == 2
        assert tr.sent_to == [("peer1", uint8(2), None), ("peer1", uint8(1), None), ("peer2", uint8(1), None)]


@pytest.mark.asyncio
async def test_increment_sent_error() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        await store.add_transaction_record(tr1)
        tr = await store.get_transaction_record(tr1.name)
        assert tr.sent == 0
        assert tr.sent_to == []

        await store.increment_sent(tr1.name, "peer1", MempoolInclusionStatus.FAILED, Err.MEMPOOL_NOT_INITIALIZED)
        tr = await store.get_transaction_record(tr1.name)
        assert tr.sent == 1
        assert tr.sent_to == [("peer1", uint8(3), "MEMPOOL_NOT_INITIALIZED")]


def test_filter_ok_mempool_status() -> None:
    assert filter_ok_mempool_status([("peer1", uint8(1), None)]) == []
    assert filter_ok_mempool_status([("peer1", uint8(2), None)]) == []
    assert filter_ok_mempool_status([("peer1", uint8(3), None)]) == [("peer1", uint8(3), None)]
    assert filter_ok_mempool_status(
        [("peer1", uint8(2), None), ("peer1", uint8(1), None), ("peer1", uint8(3), None)]
    ) == [("peer1", uint8(3), None)]

    assert filter_ok_mempool_status([("peer1", uint8(3), "message does not matter")]) == [
        ("peer1", uint8(3), "message does not matter")
    ]
    assert filter_ok_mempool_status([("peer1", uint8(2), "message does not matter")]) == []


@pytest.mark.asyncio
async def test_tx_reorged_update() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr = dataclasses.replace(tr1, sent=2, sent_to=[("peer1", uint8(1), None), ("peer2", uint8(1), None)])
        await store.add_transaction_record(tr)
        tr = await store.get_transaction_record(tr.name)
        assert tr.sent == 2
        assert tr.sent_to == [("peer1", uint8(1), None), ("peer2", uint8(1), None)]

        await store.tx_reorged(tr)
        tr = await store.get_transaction_record(tr1.name)
        assert tr.sent == 0
        assert tr.sent_to == []


@pytest.mark.asyncio
async def test_tx_reorged_add() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr = dataclasses.replace(tr1, sent=2, sent_to=[("peer1", uint8(1), None), ("peer2", uint8(1), None)])

        await store.get_transaction_record(tr.name) is None
        await store.tx_reorged(tr)
        tr = await store.get_transaction_record(tr.name)
        assert tr.sent == 0
        assert tr.sent_to == []


@pytest.mark.asyncio
async def test_get_tx_record() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr2 = dataclasses.replace(tr1, name=token_bytes(32))
        tr3 = dataclasses.replace(tr1, name=token_bytes(32))

        assert await store.get_transaction_record(tr1.name) is None
        await store.add_transaction_record(tr1)
        assert await store.get_transaction_record(tr1.name) == tr1

        assert await store.get_transaction_record(tr2.name) is None
        await store.add_transaction_record(tr2)
        assert await store.get_transaction_record(tr2.name) == tr2

        assert await store.get_transaction_record(tr3.name) is None
        await store.add_transaction_record(tr3)
        assert await store.get_transaction_record(tr3.name) == tr3

        assert await store.get_transaction_record(tr1.name) == tr1
        assert await store.get_transaction_record(tr2.name) == tr2
        assert await store.get_transaction_record(tr3.name) == tr3


@pytest.mark.asyncio
async def test_get_farming_rewards() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        test_trs: List[TransactionRecord] = []
        # tr1 is type OUTGOING_TX

        for conf in [True, False]:
            for type in [
                TransactionType.INCOMING_TX,
                TransactionType.OUTGOING_TX,
                TransactionType.COINBASE_REWARD,
                TransactionType.FEE_REWARD,
                TransactionType.INCOMING_TRADE,
                TransactionType.OUTGOING_TRADE,
            ]:
                test_trs.append(
                    dataclasses.replace(
                        tr1,
                        name=token_bytes(32),
                        confirmed=conf,
                        confirmed_at_height=uint32(100 if conf else 0),
                        type=type,
                    )
                )

        for tr in test_trs:
            await store.add_transaction_record(tr)
            assert await store.get_transaction_record(tr.name) == tr

        rewards = await store.get_farming_rewards()
        assert len(rewards) == 2
        assert test_trs[2] in rewards
        assert test_trs[3] in rewards


@pytest.mark.asyncio
async def test_get_all_unconfirmed() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr2 = dataclasses.replace(tr1, name=token_bytes(32), confirmed=True, confirmed_at_height=uint32(100))
        await store.add_transaction_record(tr1)
        await store.add_transaction_record(tr2)

        assert await store.get_all_unconfirmed() == [tr1]


@pytest.mark.asyncio
async def test_get_unconfirmed_for_wallet() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr2 = dataclasses.replace(tr1, name=token_bytes(32), confirmed=True, confirmed_at_height=uint32(100))
        tr3 = dataclasses.replace(tr1, name=token_bytes(32), wallet_id=2)
        tr4 = dataclasses.replace(tr2, name=token_bytes(32), wallet_id=2)
        await store.add_transaction_record(tr1)
        await store.add_transaction_record(tr2)
        await store.add_transaction_record(tr3)
        await store.add_transaction_record(tr4)

        assert await store.get_unconfirmed_for_wallet(1) == [tr1]
        assert await store.get_unconfirmed_for_wallet(2) == [tr3]


@pytest.mark.asyncio
async def test_transaction_count_for_wallet() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr2 = dataclasses.replace(tr1, name=token_bytes(32), wallet_id=2)

        # 5 transactions in wallet_id 1
        await store.add_transaction_record(tr1)
        await store.add_transaction_record(dataclasses.replace(tr1, name=token_bytes(32)))
        await store.add_transaction_record(dataclasses.replace(tr1, name=token_bytes(32)))
        await store.add_transaction_record(dataclasses.replace(tr1, name=token_bytes(32)))
        await store.add_transaction_record(dataclasses.replace(tr1, name=token_bytes(32)))

        # 2 transactions in wallet_id 2
        await store.add_transaction_record(tr2)
        await store.add_transaction_record(dataclasses.replace(tr2, name=token_bytes(32)))

        assert await store.get_transaction_count_for_wallet(1) == 5
        assert await store.get_transaction_count_for_wallet(2) == 2


@pytest.mark.asyncio
async def test_all_transactions_for_wallet() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        test_trs: List[TransactionRecord] = []
        for wallet_id in [1, 2]:
            for type in [
                TransactionType.INCOMING_TX,
                TransactionType.OUTGOING_TX,
                TransactionType.COINBASE_REWARD,
                TransactionType.FEE_REWARD,
                TransactionType.INCOMING_TRADE,
                TransactionType.OUTGOING_TRADE,
            ]:
                test_trs.append(dataclasses.replace(tr1, name=token_bytes(32), wallet_id=wallet_id, type=type))

        for tr in test_trs:
            await store.add_transaction_record(tr)

        assert await store.get_all_transactions_for_wallet(1) == test_trs[:6]
        assert await store.get_all_transactions_for_wallet(2) == test_trs[6:]

        assert await store.get_all_transactions_for_wallet(1, TransactionType.INCOMING_TX) == [test_trs[0]]
        assert await store.get_all_transactions_for_wallet(1, TransactionType.OUTGOING_TX) == [test_trs[1]]
        assert await store.get_all_transactions_for_wallet(1, TransactionType.INCOMING_TRADE) == [test_trs[4]]
        assert await store.get_all_transactions_for_wallet(1, TransactionType.OUTGOING_TRADE) == [test_trs[5]]

        assert await store.get_all_transactions_for_wallet(2, TransactionType.INCOMING_TX) == [test_trs[6]]
        assert await store.get_all_transactions_for_wallet(2, TransactionType.OUTGOING_TX) == [test_trs[7]]
        assert await store.get_all_transactions_for_wallet(2, TransactionType.INCOMING_TRADE) == [test_trs[10]]
        assert await store.get_all_transactions_for_wallet(2, TransactionType.OUTGOING_TRADE) == [test_trs[11]]


def cmp(lhs: List[Any], rhs: List[Any]) -> bool:
    if len(rhs) != len(lhs):
        return False

    for e in lhs:
        if e not in rhs:
            return False
    return True


@pytest.mark.asyncio
async def test_get_all_transactions() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        test_trs: List[TransactionRecord] = []
        assert await store.get_all_transactions() == []
        for wallet_id in [1, 2, 3, 4]:
            test_trs.append(dataclasses.replace(tr1, name=token_bytes(32), wallet_id=wallet_id))

        for tr in test_trs:
            await store.add_transaction_record(tr)

        all_trs = await store.get_all_transactions()
        assert cmp(all_trs, test_trs)


@pytest.mark.asyncio
async def test_get_transaction_above() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        test_trs: List[TransactionRecord] = []
        assert await store.get_transaction_above(uint32(0)) == []
        for height in range(10):
            test_trs.append(dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(height)))

        for tr in test_trs:
            await store.add_transaction_record(tr)

        for height in range(10):
            trs = await store.get_transaction_above(uint32(height))
            assert cmp(trs, test_trs[height + 1 :])


@pytest.mark.asyncio
async def test_get_tx_by_trade_id() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr2 = dataclasses.replace(tr1, name=token_bytes(32), trade_id=token_bytes(32))
        tr3 = dataclasses.replace(tr1, name=token_bytes(32), trade_id=token_bytes(32))
        tr4 = dataclasses.replace(tr1, name=token_bytes(32))

        assert await store.get_transactions_by_trade_id(tr1.trade_id) == []
        await store.add_transaction_record(tr1)
        assert await store.get_transactions_by_trade_id(tr1.trade_id) == [tr1]

        assert await store.get_transactions_by_trade_id(tr2.trade_id) == []
        await store.add_transaction_record(tr2)
        assert await store.get_transactions_by_trade_id(tr2.trade_id) == [tr2]

        assert await store.get_transactions_by_trade_id(tr3.trade_id) == []
        await store.add_transaction_record(tr3)
        assert await store.get_transactions_by_trade_id(tr3.trade_id) == [tr3]

        # tr1 and tr4 have the same trade_id
        assert await store.get_transactions_by_trade_id(tr4.trade_id) == [tr1]
        await store.add_transaction_record(tr4)
        assert cmp(await store.get_transactions_by_trade_id(tr4.trade_id), [tr1, tr4])

        assert cmp(await store.get_transactions_by_trade_id(tr1.trade_id), [tr1, tr4])
        assert await store.get_transactions_by_trade_id(tr2.trade_id) == [tr2]
        assert await store.get_transactions_by_trade_id(tr3.trade_id) == [tr3]
        assert cmp(await store.get_transactions_by_trade_id(tr4.trade_id), [tr1, tr4])


@pytest.mark.asyncio
async def test_rollback_to_block() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        test_trs: List[TransactionRecord] = []
        for height in range(10):
            test_trs.append(dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(height)))

        for tr in test_trs:
            await store.add_transaction_record(tr)

        await store.rollback_to_block(uint32(6))
        all_trs = await store.get_all_transactions()
        assert cmp(all_trs, test_trs[:7])

        await store.rollback_to_block(uint32(5))
        all_trs = await store.get_all_transactions()
        assert cmp(all_trs, test_trs[:6])


@pytest.mark.asyncio
async def test_delete_unconfirmed() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr2 = dataclasses.replace(tr1, name=token_bytes(32), confirmed=True)
        tr3 = dataclasses.replace(tr1, name=token_bytes(32), confirmed=True, wallet_id=2)
        tr4 = dataclasses.replace(tr1, name=token_bytes(32), wallet_id=2)

        await store.add_transaction_record(tr1)
        await store.add_transaction_record(tr2)
        await store.add_transaction_record(tr3)
        await store.add_transaction_record(tr4)

        assert cmp(await store.get_all_transactions(), [tr1, tr2, tr3, tr4])
        await store.delete_unconfirmed_transactions(1)
        assert cmp(await store.get_all_transactions(), [tr2, tr3, tr4])
        await store.delete_unconfirmed_transactions(2)
        assert cmp(await store.get_all_transactions(), [tr2, tr3])


@pytest.mark.asyncio
async def test_get_transactions_between_confirmed() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr2 = dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(1))
        tr3 = dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(2))
        tr4 = dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(3))
        tr5 = dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(4))

        await store.add_transaction_record(tr1)
        await store.add_transaction_record(tr2)
        await store.add_transaction_record(tr3)
        await store.add_transaction_record(tr4)
        await store.add_transaction_record(tr5)

        # test different limits
        assert await store.get_transactions_between(1, 0, 1) == [tr1]
        assert await store.get_transactions_between(1, 0, 2) == [tr1, tr2]
        assert await store.get_transactions_between(1, 0, 3) == [tr1, tr2, tr3]
        assert await store.get_transactions_between(1, 0, 100) == [tr1, tr2, tr3, tr4, tr5]

        # test different start offsets
        assert await store.get_transactions_between(1, 1, 100) == [tr2, tr3, tr4, tr5]
        assert await store.get_transactions_between(1, 2, 100) == [tr3, tr4, tr5]
        assert await store.get_transactions_between(1, 3, 100) == [tr4, tr5]

        # wallet 2 is empty
        assert await store.get_transactions_between(2, 0, 100) == []

        # reverse

        # test different limits
        assert await store.get_transactions_between(1, 0, 1, reverse=True) == [tr5]
        assert await store.get_transactions_between(1, 0, 2, reverse=True) == [tr5, tr4]
        assert await store.get_transactions_between(1, 0, 3, reverse=True) == [tr5, tr4, tr3]
        assert await store.get_transactions_between(1, 0, 100, reverse=True) == [tr5, tr4, tr3, tr2, tr1]

        # test different start offsets
        assert await store.get_transactions_between(1, 1, 100, reverse=True) == [tr4, tr3, tr2, tr1]
        assert await store.get_transactions_between(1, 2, 100, reverse=True) == [tr3, tr2, tr1]
        assert await store.get_transactions_between(1, 3, 100, reverse=True) == [tr2, tr1]


@pytest.mark.asyncio
async def test_get_transactions_between_relevance() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        t1 = dataclasses.replace(
            tr1, name=token_bytes(32), confirmed=False, confirmed_at_height=uint32(2), created_at_time=1000
        )
        t2 = dataclasses.replace(
            tr1, name=token_bytes(32), confirmed=False, confirmed_at_height=uint32(2), created_at_time=999
        )
        t3 = dataclasses.replace(
            tr1, name=token_bytes(32), confirmed=False, confirmed_at_height=uint32(1), created_at_time=1000
        )
        t4 = dataclasses.replace(
            tr1, name=token_bytes(32), confirmed=False, confirmed_at_height=uint32(1), created_at_time=999
        )

        t5 = dataclasses.replace(
            tr1, name=token_bytes(32), confirmed=True, confirmed_at_height=uint32(2), created_at_time=1000
        )
        t6 = dataclasses.replace(
            tr1, name=token_bytes(32), confirmed=True, confirmed_at_height=uint32(2), created_at_time=999
        )
        t7 = dataclasses.replace(
            tr1, name=token_bytes(32), confirmed=True, confirmed_at_height=uint32(1), created_at_time=1000
        )
        t8 = dataclasses.replace(
            tr1, name=token_bytes(32), confirmed=True, confirmed_at_height=uint32(1), created_at_time=999
        )

        await store.add_transaction_record(t1)
        await store.add_transaction_record(t2)
        await store.add_transaction_record(t3)
        await store.add_transaction_record(t4)
        await store.add_transaction_record(t5)
        await store.add_transaction_record(t6)
        await store.add_transaction_record(t7)
        await store.add_transaction_record(t8)

        # test different limits
        assert await store.get_transactions_between(1, 0, 1, sort_key="RELEVANCE") == [t1]
        assert await store.get_transactions_between(1, 0, 2, sort_key="RELEVANCE") == [t1, t2]
        assert await store.get_transactions_between(1, 0, 3, sort_key="RELEVANCE") == [t1, t2, t3]
        assert await store.get_transactions_between(1, 0, 100, sort_key="RELEVANCE") == [t1, t2, t3, t4, t5, t6, t7, t8]

        # test different start offsets
        assert await store.get_transactions_between(1, 1, 100, sort_key="RELEVANCE") == [t2, t3, t4, t5, t6, t7, t8]
        assert await store.get_transactions_between(1, 2, 100, sort_key="RELEVANCE") == [t3, t4, t5, t6, t7, t8]
        assert await store.get_transactions_between(1, 3, 100, sort_key="RELEVANCE") == [t4, t5, t6, t7, t8]
        assert await store.get_transactions_between(1, 4, 100, sort_key="RELEVANCE") == [t5, t6, t7, t8]

        # wallet 2 is empty
        assert await store.get_transactions_between(2, 0, 100, sort_key="RELEVANCE") == []

        # reverse

        # test different limits
        assert await store.get_transactions_between(1, 0, 1, sort_key="RELEVANCE", reverse=True) == [t8]
        assert await store.get_transactions_between(1, 0, 2, sort_key="RELEVANCE", reverse=True) == [t8, t7]
        assert await store.get_transactions_between(1, 0, 3, sort_key="RELEVANCE", reverse=True) == [t8, t7, t6]
        assert await store.get_transactions_between(1, 0, 100, sort_key="RELEVANCE", reverse=True) == [
            t8,
            t7,
            t6,
            t5,
            t4,
            t3,
            t2,
            t1,
        ]

        # test different start offsets
        assert await store.get_transactions_between(1, 1, 100, sort_key="RELEVANCE", reverse=True) == [
            t7,
            t6,
            t5,
            t4,
            t3,
            t2,
            t1,
        ]
        assert await store.get_transactions_between(1, 2, 100, sort_key="RELEVANCE", reverse=True) == [
            t6,
            t5,
            t4,
            t3,
            t2,
            t1,
        ]
        assert await store.get_transactions_between(1, 3, 100, sort_key="RELEVANCE", reverse=True) == [
            t5,
            t4,
            t3,
            t2,
            t1,
        ]


@pytest.mark.asyncio
async def test_get_transactions_between_to_puzzle_hash() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        ph1 = token_bytes(32)
        ph2 = token_bytes(32)

        tr2 = dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(1), to_puzzle_hash=ph1)
        tr3 = dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(2), to_puzzle_hash=ph1)
        tr4 = dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(3), to_puzzle_hash=ph2)
        tr5 = dataclasses.replace(tr1, name=token_bytes(32), confirmed_at_height=uint32(4), to_puzzle_hash=ph2)

        await store.add_transaction_record(tr1)
        await store.add_transaction_record(tr2)
        await store.add_transaction_record(tr3)
        await store.add_transaction_record(tr4)
        await store.add_transaction_record(tr5)

        # test different limits
        assert await store.get_transactions_between(1, 0, 100, to_puzzle_hash=ph1) == [tr2, tr3]
        assert await store.get_transactions_between(1, 0, 100, to_puzzle_hash=ph2) == [tr4, tr5]

        # test different start offsets
        assert await store.get_transactions_between(1, 1, 100, to_puzzle_hash=ph1) == [tr3]
        assert await store.get_transactions_between(1, 1, 100, to_puzzle_hash=ph2) == [tr5]

        # reverse

        # test different limits
        assert await store.get_transactions_between(1, 0, 100, to_puzzle_hash=ph1, reverse=True) == [tr3, tr2]
        assert await store.get_transactions_between(1, 0, 100, to_puzzle_hash=ph2, reverse=True) == [tr5, tr4]

        # test different start offsets
        assert await store.get_transactions_between(1, 1, 100, to_puzzle_hash=ph1, reverse=True) == [tr2]
        assert await store.get_transactions_between(1, 1, 100, to_puzzle_hash=ph2, reverse=True) == [tr4]


@pytest.mark.asyncio
async def test_get_not_sent() -> None:
    async with DBConnection(1) as db_wrapper:
        store = await WalletTransactionStore.create(db_wrapper)

        tr2 = dataclasses.replace(tr1, name=token_bytes(32), confirmed=True, confirmed_at_height=uint32(1))
        tr3 = dataclasses.replace(tr1, name=token_bytes(32))
        tr4 = dataclasses.replace(tr1, name=token_bytes(32))

        await store.add_transaction_record(tr1)
        await store.add_transaction_record(tr2)
        await store.add_transaction_record(tr3)
        await store.add_transaction_record(tr4)

        not_sent = await store.get_not_sent()
        assert cmp(not_sent, [tr1, tr3, tr4])

        not_sent = await store.get_not_sent()
        assert cmp(not_sent, [tr1, tr3, tr4])

        not_sent = await store.get_not_sent()
        assert cmp(not_sent, [tr1, tr3, tr4])

        not_sent = await store.get_not_sent()
        assert cmp(not_sent, [tr1, tr3, tr4])

        not_sent = await store.get_not_sent()
        assert cmp(not_sent, [tr1, tr3, tr4])

        # the 6th time we call this function, we don't get any unsent txs
        not_sent = await store.get_not_sent()
        assert cmp(not_sent, [])

        # TODO: also cover include_accepted_txs=True
