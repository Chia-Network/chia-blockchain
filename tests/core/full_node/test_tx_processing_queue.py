from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from secrets import token_bytes
from typing import List, Optional, cast

import pytest

from chia.full_node.tx_processing_queue import TransactionQueue, TransactionQueueFull
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.transaction_queue_entry import TransactionQueueEntry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FakeTransactionQueueEntry:
    index: int
    peer_id: Optional[bytes32]


def get_transaction_queue_entry(peer_id: Optional[bytes32], tx_index: int) -> TransactionQueueEntry:  # easy shortcut
    return cast(TransactionQueueEntry, FakeTransactionQueueEntry(index=tx_index, peer_id=peer_id))


def get_peer_id() -> bytes32:
    return bytes32(token_bytes(32))


@pytest.mark.asyncio
async def test_local_txs() -> None:
    transaction_queue = TransactionQueue(1000, log)
    # test 1 tx
    first_tx = get_transaction_queue_entry(None, 0)
    await transaction_queue.put(first_tx, None)

    result1 = await transaction_queue.pop()

    assert result1 == first_tx

    # test 2000 txs
    num_txs = 2000
    list_txs = [get_transaction_queue_entry(get_peer_id(), i) for i in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, None)

    resulting_txs = []
    for _ in range(num_txs):
        resulting_txs.append(await transaction_queue.pop())

    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i]


@pytest.mark.asyncio
async def test_one_peer_and_await() -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_txs = 100
    peer_id = get_peer_id()

    list_txs = [get_transaction_queue_entry(peer_id, i) for i in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, peer_id)

    # test transaction priority
    local_txs = [get_transaction_queue_entry(None, i) for i in range(int(num_txs / 5))]  # 20 txs
    for tx in local_txs:
        await transaction_queue.put(tx, None)

    resulting_txs = []
    for _ in range(num_txs + len(local_txs)):
        resulting_txs.append(await transaction_queue.pop())

    for i in range(num_txs + len(local_txs)):
        if i < len(local_txs):
            assert local_txs[i] == resulting_txs[i]  # first 20 should come from local
        else:
            assert list_txs[i - 20] == resulting_txs[i]

    # now we validate that the pop command is blocking
    task = asyncio.create_task(transaction_queue.pop())
    with pytest.raises(asyncio.InvalidStateError):  # task is not done, so we expect an error when getting result
        task.result()
    # add a tx to test task completion
    await transaction_queue.put(get_transaction_queue_entry(None, 0), None)
    await asyncio.wait_for(task, 1)  # we should never time out here


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

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())

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

    # test failure case.
    with pytest.raises(TransactionQueueFull):
        await transaction_queue.put(get_transaction_queue_entry(peer_ids[0], 1001), peer_ids[0])

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())


@pytest.mark.asyncio
async def test_queue_cleanup_and_fairness() -> None:
    transaction_queue = TransactionQueue(1000, log)
    peer_a = get_peer_id()
    peer_b = get_peer_id()
    peer_c = get_peer_id()

    # 2 for a, 1 for b, 2 for c
    peer_tx_a = [get_transaction_queue_entry(peer_a, i) for i in range(2)]
    peer_tx_b = [get_transaction_queue_entry(peer_b, 0)]
    peer_tx_c = [get_transaction_queue_entry(peer_c, i) for i in range(2)]

    list_txs = peer_tx_a + peer_tx_b + peer_tx_c
    for tx in list_txs:
        await transaction_queue.put(tx, tx.peer_id)  # type: ignore[attr-defined]

    resulting_ids = []
    for _ in range(3):  # we validate we get one transaction per peer
        resulting_ids.append((await transaction_queue.pop()).peer_id)  # type: ignore[attr-defined]
    assert [peer_a, peer_b, peer_c] == resulting_ids  # all peers have been properly included in the queue.
    second_resulting_ids = []
    for _ in range(2):  # we validate that we properly queue the last 2 transactions
        second_resulting_ids.append((await transaction_queue.pop()).peer_id)  # type: ignore[attr-defined]
    assert [peer_a, peer_c] == second_resulting_ids
