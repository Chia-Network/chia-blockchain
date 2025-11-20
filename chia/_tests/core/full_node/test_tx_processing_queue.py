from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import cast

import pytest
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.full_node.tx_processing_queue import PeerWithTx, TransactionQueue, TransactionQueueEntry, TransactionQueueFull
from chia.util.task_referencer import create_referenced_task

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FakeTransactionQueueEntry:
    index: int = field(compare=False)
    peer_id: bytes32 | None = field(compare=False)
    peers_with_tx: dict[bytes32, PeerWithTx] | None = field(compare=False)


def get_transaction_queue_entry(
    peer_id: bytes32 | None, tx_index: int, peers_with_tx: dict[bytes32, PeerWithTx] | None = None
) -> TransactionQueueEntry:  # easy shortcut
    if peers_with_tx is None:
        peers_with_tx = {}
    return cast(TransactionQueueEntry, FakeTransactionQueueEntry(tx_index, peer_id, peers_with_tx))


@pytest.mark.anyio
async def test_local_txs(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log)
    # test 1 tx
    first_tx = get_transaction_queue_entry(None, 0)
    await transaction_queue.put(first_tx, None)

    result1 = await transaction_queue.pop()

    assert result1 == first_tx

    # test 2000 txs
    num_txs = 2000
    list_txs = [get_transaction_queue_entry(bytes32.random(seeded_random), i) for i in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, None)

    resulting_txs = []
    for _ in range(num_txs):
        resulting_txs.append(await transaction_queue.pop())

    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i]


@pytest.mark.anyio
async def test_one_peer_and_await(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_txs = 100
    peer_id = bytes32.random(seeded_random)

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
    task = create_referenced_task(transaction_queue.pop())
    with pytest.raises(asyncio.InvalidStateError):  # task is not done, so we expect an error when getting result
        task.result()
    # add a tx to test task completion
    await transaction_queue.put(get_transaction_queue_entry(None, 0), None)
    await asyncio.wait_for(task, 1)  # we should never time out here


@pytest.mark.anyio
async def test_lots_of_peers(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_peers = 1000
    num_txs = 100
    total_txs = num_txs * num_peers
    peer_ids: list[bytes32] = [bytes32.random(seeded_random) for _ in range(num_peers)]

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


@pytest.mark.anyio
async def test_full_queue(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_peers = 100
    num_txs = 1000
    total_txs = num_txs * num_peers
    peer_ids: list[bytes32] = [bytes32.random(seeded_random) for _ in range(num_peers)]

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


@pytest.mark.anyio
async def test_queue_cleanup_and_fairness(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log)
    peer_a = bytes32.random(seeded_random)
    peer_b = bytes32.random(seeded_random)
    peer_c = bytes32.random(seeded_random)

    higher_tx_cost = uint64(20)
    lower_tx_cost = uint64(10)
    higher_tx_fee = uint64(5)
    lower_tx_fee = uint64(1)
    # 2 for a, 1 for b, 2 for c
    peer_tx_a = [
        get_transaction_queue_entry(peer_a, 0, {peer_a: PeerWithTx(str(peer_a), lower_tx_fee, higher_tx_cost)}),
        get_transaction_queue_entry(peer_a, 1, {peer_a: PeerWithTx(str(peer_a), higher_tx_fee, lower_tx_cost)}),
    ]
    peer_tx_b = [
        get_transaction_queue_entry(peer_b, 0, {peer_b: PeerWithTx(str(peer_b), higher_tx_fee, lower_tx_cost)})
    ]
    peer_tx_c = [
        get_transaction_queue_entry(peer_c, 0, {peer_c: PeerWithTx(str(peer_c), higher_tx_fee, lower_tx_cost)}),
        get_transaction_queue_entry(peer_c, 1, {peer_c: PeerWithTx(str(peer_c), lower_tx_fee, higher_tx_cost)}),
    ]

    list_txs = peer_tx_a + peer_tx_b + peer_tx_c
    for tx in list_txs:
        await transaction_queue.put(tx, tx.peer_id)  # type: ignore[attr-defined]

    entries = []
    for _ in range(3):  # we validate we get one transaction per peer
        entry = await transaction_queue.pop()
        entries.append((entry.peer_id, entry.index))  # type: ignore[attr-defined]
    assert [(peer_a, 1), (peer_b, 0), (peer_c, 0)] == entries  # all peers have been properly included in the queue.
    second_entries = []
    for _ in range(2):  # we validate that we properly queue the last 2 transactions
        entry = await transaction_queue.pop()
        second_entries.append((entry.peer_id, entry.index))  # type: ignore[attr-defined]
    assert [(peer_a, 0), (peer_c, 1)] == second_entries


@pytest.mark.anyio
async def test_peer_queue_prioritization_fallback() -> None:
    """
    Tests prioritization fallback, when `peer_id` is not in `peers_with_tx` and
    we compute the fee per cost (for priority) using values from the peer with
    the highest advertised cost, even if that results in a lower fee per cost.
    """
    queue = TransactionQueue(42, log)
    peer1 = bytes32.random()
    peer2 = bytes32.random()
    # We'll be using this peer to test the fallback, so we don't include it in
    # peers with transactions maps.
    peer3 = bytes32.random()
    peers_with_tx1 = {
        # This has FPC of 5.0
        peer1: PeerWithTx(str(peer1), uint64(10), uint64(2)),
        # This has FPC of 2.0 but higher advertised cost
        peer2: PeerWithTx(str(peer2), uint64(20), uint64(10)),
    }
    tx1 = get_transaction_queue_entry(peer3, 0, peers_with_tx1)
    await queue.put(tx1, peer3)
    peers_with_tx2 = {
        # This has FPC of 3.0
        peer1: PeerWithTx(str(peer1), uint64(30), uint64(10)),
        # This has FPC of 4.0 but lower advertised cost
        peer2: PeerWithTx(str(peer2), uint64(20), uint64(5)),
    }
    tx2 = get_transaction_queue_entry(peer3, 1, peers_with_tx2)
    await queue.put(tx2, peer3)
    # tx2 gets top priority with FPC 3.0 instead of 4.0 due to higher cost fallback
    assert queue._queue_dict[peer3]._queue[0][0] == -3.0  # type: ignore[attr-defined]
    entry1 = await queue.pop()
    assert entry1.index == 1  # type: ignore[attr-defined]
    # tx1 comes next with FPC 2.0 instead of 5.0 due to higher cost fallback
    assert queue._queue_dict[peer3]._queue[0][0] == -2.0  # type: ignore[attr-defined]
    entry2 = await queue.pop()
    assert entry2.index == 0  # type: ignore[attr-defined]
