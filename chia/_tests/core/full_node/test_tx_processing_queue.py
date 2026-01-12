from __future__ import annotations

import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from typing import cast

import pytest
from chia_rs import G2Element, SpendBundle
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.full_node.tx_processing_queue import PeerWithTx, TransactionQueue, TransactionQueueEntry, TransactionQueueFull
from chia.simulator.block_tools import test_constants
from chia.util.task_referencer import create_referenced_task

log = logging.getLogger(__name__)

TEST_MAX_TX_CLVM_COST = uint64(test_constants.MAX_BLOCK_COST_CLVM // 2)


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
    transaction_queue = TransactionQueue(1000, log, max_tx_clvm_cost=TEST_MAX_TX_CLVM_COST)
    # test 1 tx
    first_tx = get_transaction_queue_entry(None, 0)
    transaction_queue.put(first_tx, None)

    result1 = await transaction_queue.pop()

    assert result1 == first_tx

    # test 2000 txs
    num_txs = 2000
    list_txs = [get_transaction_queue_entry(bytes32.random(seeded_random), i) for i in range(num_txs)]
    for tx in list_txs:
        transaction_queue.put(tx, None)

    resulting_txs = []
    for _ in range(num_txs):
        resulting_txs.append(await transaction_queue.pop())

    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i]


@pytest.mark.anyio
async def test_one_peer_and_await(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log, max_tx_clvm_cost=TEST_MAX_TX_CLVM_COST)
    num_txs = 100
    peer_id = bytes32.random(seeded_random)

    list_txs = [get_transaction_queue_entry(peer_id, i) for i in range(num_txs)]
    for tx in list_txs:
        transaction_queue.put(tx, peer_id)

    # test transaction priority
    local_txs = [get_transaction_queue_entry(None, i) for i in range(int(num_txs / 5))]  # 20 txs
    for tx in local_txs:
        transaction_queue.put(tx, None)

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
    transaction_queue.put(get_transaction_queue_entry(None, 0), None)
    await asyncio.wait_for(task, 1)  # we should never time out here


@pytest.mark.anyio
async def test_lots_of_peers(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log, max_tx_clvm_cost=TEST_MAX_TX_CLVM_COST)
    num_peers = 1000
    num_txs = 100
    total_txs = num_txs * num_peers
    peer_ids: list[bytes32] = [bytes32.random(seeded_random) for _ in range(num_peers)]

    # 100 txs per peer
    list_txs = [get_transaction_queue_entry(peer_id, i) for peer_id in peer_ids for i in range(num_txs)]
    for tx in list_txs:
        transaction_queue.put(tx, tx.peer_id)  # type: ignore[attr-defined]

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())

    # There are 1000 peers, so each peer will have one transaction processed every 1000 iterations.
    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i * 1000]


@pytest.mark.anyio
async def test_full_queue(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log, max_tx_clvm_cost=TEST_MAX_TX_CLVM_COST)
    num_peers = 100
    num_txs = 1000
    total_txs = num_txs * num_peers
    peer_ids: list[bytes32] = [bytes32.random(seeded_random) for _ in range(num_peers)]

    # 999 txs per peer then 1 to fail later
    list_txs = [get_transaction_queue_entry(peer_id, i) for peer_id in peer_ids for i in range(num_txs)]
    for tx in list_txs:
        transaction_queue.put(tx, tx.peer_id)  # type: ignore[attr-defined]

    # test failure case.
    with pytest.raises(TransactionQueueFull):
        transaction_queue.put(get_transaction_queue_entry(peer_ids[0], 1001), peer_ids[0])

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())


@pytest.mark.anyio
async def test_queue_cleanup_and_fairness(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log, max_tx_clvm_cost=TEST_MAX_TX_CLVM_COST)
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
        transaction_queue.put(tx, tx.peer_id)  # type: ignore[attr-defined]

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


def test_tx_queue_entry_order_compare() -> None:
    """
    Tests that `TransactionQueueEntry` orders and compares using transaction
    IDs regardless of other fields.
    """
    # Let's create two items with the same transaction ID but different data
    sb = SpendBundle([], G2Element())
    sb_name = sb.name()
    item1 = TransactionQueueEntry(
        transaction=sb, transaction_bytes=bytes(sb), spend_name=sb_name, peer=None, test=False, peers_with_tx={}
    )
    item2 = TransactionQueueEntry(
        transaction=sb, transaction_bytes=None, spend_name=sb_name, peer=None, test=True, peers_with_tx={}
    )
    # They should be ordered and compared (considered equal) by `spend_name`
    # regardless of other fields.
    assert (item1 < item2) is False
    assert item1 == item2


@pytest.mark.anyio
async def test_peer_queue_prioritization_fallback() -> None:
    """
    Tests prioritization fallback, when `peer_id` is not in `peers_with_tx`.
    """
    queue = TransactionQueue(42, log, max_tx_clvm_cost=TEST_MAX_TX_CLVM_COST)
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
    queue.put(tx1, peer3)
    peers_with_tx2 = {
        # This has FPC of 3.0
        peer1: PeerWithTx(str(peer1), uint64(30), uint64(10)),
        # This has FPC of 4.0 but lower advertised cost
        peer2: PeerWithTx(str(peer2), uint64(20), uint64(5)),
        # This has FPC of 1.0 but lower advertised cost
        peer3: PeerWithTx(str(peer3), uint64(4), uint64(4)),
    }
    tx2 = get_transaction_queue_entry(peer3, 1, peers_with_tx2)
    queue.put(tx2, peer3)
    # tx2 gets top priority with FPC 1.0
    assert math.isclose(queue._peers_transactions_queues[peer3].priority_queue.queue[0][0], -1.0)
    entry = await queue.pop()
    # NOTE: This whole test file uses `index` as an addition to
    # `TransactionQueueEntry` for easier testing, hence this type ignore here
    # and everywhere else.
    assert entry.index == 1  # type: ignore[attr-defined]
    # tx1 comes next due to lowest priority fallback
    assert math.isinf(queue._peers_transactions_queues[peer3].priority_queue.queue[0][0])
    entry = await queue.pop()
    assert entry.index == 0  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_normal_queue_deficit_round_robin() -> None:
    """
    Covers the deficit round robin behavior of the normal transaction queue where
    we cycle through peers and pick their top transactions when their deficit
    counters allow them to afford it, and we ensure that their deficit counters
    adapt accordingly.
    This also covers the case where a peer's top transaction does not advertise
    cost, so that falls back to `max_tx_clvm_cost`.
    This also covers the cleanup behavior where peers with no remaining
    transactions are removed periodically (each 100 pop) from the queue.
    """
    test_max_tx_clvm_cost = uint64(20)
    queue = TransactionQueue(42, log, max_tx_clvm_cost=test_max_tx_clvm_cost)
    peer1 = bytes32.random()
    peer2 = bytes32.random()
    peer3 = bytes32.random()
    peer4 = bytes32.random()
    test_fee = uint64(42)
    # We give this one the highest cost
    tx1 = get_transaction_queue_entry(peer1, 0, {peer1: PeerWithTx(str(peer1), test_fee, uint64(15))})
    queue.put(tx1, peer1)
    # And this one the lowest cost
    tx2 = get_transaction_queue_entry(peer2, 1, {peer2: PeerWithTx(str(peer2), test_fee, uint64(5))})
    queue.put(tx2, peer2)
    # And this one a cost in between
    tx3 = get_transaction_queue_entry(peer3, 2, {peer3: PeerWithTx(str(peer3), test_fee, uint64(10))})
    queue.put(tx3, peer3)
    # This one has no cost information so its top transaction's advertised cost
    # falls back to `test_max_tx_clvm_cost`.
    tx4 = get_transaction_queue_entry(peer4, 3, {})
    queue.put(tx4, peer4)
    # When we try to pop a transaction, none of the peers initially can
    # afford to send their top transactions, so we add the lowest cost among
    # transactions (5) to all the peers' deficit counters and try again. This
    # makes peer2 able to send its transaction tx2.
    entry = await queue.pop()
    assert entry.index == 1  # type: ignore[attr-defined]
    assert queue._list_cursor == 2
    assert queue._peers_transactions_queues[peer1].deficit == 5
    assert queue._peers_transactions_queues[peer2].deficit == 0
    assert queue._peers_transactions_queues[peer3].deficit == 5
    assert queue._peers_transactions_queues[peer4].deficit == 5
    # Now peer3, peer4 and peer1 can't afford to send their top transactions so
    # we add the lowest cost among transactions (10) to their deficit counters
    # and try again. This makes peer3 able to send its transaction tx3.
    entry = await queue.pop()
    assert entry.index == 2  # type: ignore[attr-defined]
    assert queue._list_cursor == 3
    assert queue._peers_transactions_queues[peer1].deficit == 15
    assert queue._peers_transactions_queues[peer2].deficit == 0
    assert queue._peers_transactions_queues[peer3].deficit == 0
    assert queue._peers_transactions_queues[peer4].deficit == 15
    # Let's force cleanup to happen on the next pop
    queue._cleanup_counter = 99
    # Now peer4 can't afford to send its top transaction (20) but peer1 can
    # send tx1 (15) so it does.
    entry = await queue.pop()
    assert entry.index == 0  # type: ignore[attr-defined]
    # This pop triggers cleanup, so peer1, peer2 and peer3 are removed from
    # the transaction queue (they have nothing left) and only peer4 remains.
    for peer in [peer1, peer2, peer3]:
        assert peer not in queue._index_to_peer_map
        assert peer not in queue._peers_transactions_queues
    assert len(queue._index_to_peer_map) == 1
    assert peer4 in queue._index_to_peer_map
    assert queue._list_cursor == 0
    # At this point we didn't have to increment deficit counters because peer1
    # could already afford to send its top transaction, so peer4's deficit
    # counter stays the same.
    assert queue._peers_transactions_queues[peer4].deficit == 15
    # Finally, peer4 is tried but it can't send its top transaction, which has
    # a fallback cost of `test_max_tx_clvm_cost` (20), so we add that to its
    # deficit counter, making it 35, and upon retrying now it's able to send
    # its transaction tx4.
    entry = await queue.pop()
    assert entry.index == 3  # type: ignore[attr-defined]
    assert queue._peers_transactions_queues[peer4].deficit == 0
    assert queue._list_cursor == 0
