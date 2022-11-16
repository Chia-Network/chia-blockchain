from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from random import sample
from secrets import token_bytes
from typing import List, cast

import pytest

from chia.full_node.tx_processing_queue import TransactionQueue, TransactionQueueFull
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.transaction_queue_entry import TransactionQueueEntry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FakeTransactionQueueEntry:
    index: int
    peer_id: bytes32


def get_transaction_queue_entry(peer_id: bytes32, tx_index: int) -> TransactionQueueEntry:  # easy shortcut
    return cast(TransactionQueueEntry, FakeTransactionQueueEntry(index=tx_index, peer_id=peer_id))


def get_peer_id() -> bytes32:
    return bytes32(token_bytes(32))


@pytest.mark.asyncio
async def test_local_txs() -> None:
    transaction_queue = TransactionQueue(1000, log)
    # test 1 tx
    first_tx = get_transaction_queue_entry(get_peer_id(), 0)
    await transaction_queue.put(first_tx, None)

    assert transaction_queue._index_to_peer_map == []
    assert transaction_queue._queue_length._value == 1

    result1 = await transaction_queue.pop()

    assert transaction_queue._queue_length._value == 0
    assert result1 == first_tx

    # test 2000 txs
    num_txs = 2000
    list_txs = [get_transaction_queue_entry(get_peer_id(), i) for i in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, None)

    assert transaction_queue._queue_length._value == num_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == []  # sanity checking

    resulting_txs = []
    for _ in range(num_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 0  # check that all are removed
    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i]


@pytest.mark.asyncio
async def test_one_peer_and_await() -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_txs = 100
    peer_id = bytes32(token_bytes(32))

    list_txs = [get_transaction_queue_entry(peer_id, i) for i in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, peer_id)

    assert transaction_queue._queue_length._value == num_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == [peer_id]  # sanity checking

    resulting_txs = []
    for _ in range(num_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 0  # check that all are removed
    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i]

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(transaction_queue.pop(), 1)  # check that we can't pop anymore


@pytest.mark.asyncio
async def test_lots_of_peers() -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_peers = 1000
    num_txs = 100
    total_txs = num_txs * num_peers
    peer_ids: List[bytes32] = [get_peer_id() for _ in range(num_peers)]

    # 100 txs per peer
    list_txs = [get_transaction_queue_entry(peer_id, i) for peer_id in peer_ids for i in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, tx.peer_id)  # type: ignore[attr-defined]

    assert transaction_queue._queue_length._value == total_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == peer_ids  # make sure all peers are in the map

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 0  # check that all are removed
    assert transaction_queue._index_to_peer_map == []  # we should have removed all the peer ids
    # There are 1000 peers, so each peer will have one transaction processed every 1000 iterations.
    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i * 1000]


@pytest.mark.asyncio
async def test_full_queue() -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_peers = 100
    num_txs = 1000
    total_txs = num_txs * num_peers
    peer_ids: List[bytes32] = [get_peer_id() for _ in range(num_peers)]

    # 999 txs per peer then 1 to fail later
    list_txs = [get_transaction_queue_entry(peer_id, i) for peer_id in peer_ids for i in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, tx.peer_id)  # type: ignore[attr-defined]

    assert transaction_queue._queue_length._value == total_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == peer_ids  # make sure all peers are in the map

    # test failure case.
    with pytest.raises(TransactionQueueFull):
        await transaction_queue.put(get_transaction_queue_entry(peer_ids[0], 1001), peer_ids[0])

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 0  # check that all are removed
    assert transaction_queue._index_to_peer_map == []  # we should have removed all the peer ids


@pytest.mark.asyncio
async def test_queue_cleanup_and_fairness() -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_peers = 1000
    num_txs = 100
    total_txs = num_txs * num_peers
    peer_ids: List[bytes32] = [get_peer_id() for _ in range(num_peers)]

    # 100 txs per peer
    list_txs = [get_transaction_queue_entry(peer_id, i) for peer_id in peer_ids for i in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, tx.peer_id)  # type: ignore[attr-defined]

    assert transaction_queue._queue_length._value == total_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == peer_ids  # check that all peers are in the map

    # give random peers another transaction
    peer_index = sample(range(num_peers), 10)
    peer_index.sort()  # use a sorted list to avoid stupid complexities.
    selected_peers = [peer_ids[i] for i in peer_index]
    extra_txs = [get_transaction_queue_entry(peers, 100) for peers in selected_peers]
    for tx in extra_txs:
        await transaction_queue.put(tx, tx.peer_id)  # type: ignore[attr-defined]

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 10  # check that all the first txs are removed for fairness.
    assert transaction_queue._index_to_peer_map == selected_peers  # only peers with 2 tx's.

    resulting_extra_txs = []
    for _ in range(10):
        resulting_extra_txs.append(await transaction_queue.pop())

    assert extra_txs == resulting_extra_txs  # validate that the extra txs are the same as the ones we put in.

    assert transaction_queue._queue_length._value == 0  # check that all tx's are removed
    assert transaction_queue._index_to_peer_map == []  # now there should be no peers in the map
