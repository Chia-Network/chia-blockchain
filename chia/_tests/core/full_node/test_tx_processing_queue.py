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
    spend_name: bytes32


def get_transaction_queue_entry(
    peer_id: bytes32 | None,
    tx_index: int,
    peers_with_tx: dict[bytes32, PeerWithTx] | None = None,
    spend_name: bytes32 = bytes32.random(),
) -> TransactionQueueEntry:  # easy shortcut
    if peers_with_tx is None:
        peers_with_tx = {}
    return cast(TransactionQueueEntry, FakeTransactionQueueEntry(tx_index, peer_id, peers_with_tx, spend_name))


@pytest.mark.anyio
async def test_local_txs(seeded_random: random.Random) -> None:
    transaction_queue = TransactionQueue(1000, log, TEST_MAX_TX_CLVM_COST)
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
    transaction_queue = TransactionQueue(1000, log, TEST_MAX_TX_CLVM_COST)
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
    transaction_queue = TransactionQueue(1000, log, TEST_MAX_TX_CLVM_COST)
    num_peers = 1000
    num_txs = 100
    total_txs = num_txs * num_peers
    peer_ids: list[bytes32] = sorted(bytes32.random(seeded_random) for _ in range(num_peers))

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
    transaction_queue = TransactionQueue(1000, log, TEST_MAX_TX_CLVM_COST)
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
    transaction_queue = TransactionQueue(1000, log, TEST_MAX_TX_CLVM_COST)
    [peer_a, peer_b, peer_c] = sorted([bytes32.random(seeded_random) for _ in range(3)])
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
    queue = TransactionQueue(42, log, TEST_MAX_TX_CLVM_COST)
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
    assert math.isclose(queue._normal_priority_queues[peer3].get_top_tx_priority(), -1.0)
    entry = await queue.pop()
    # NOTE: This whole test file uses `index` as an addition to
    # `TransactionQueueEntry` for easier testing, hence this type ignore here
    # and everywhere else.
    assert entry.index == 1  # type: ignore[attr-defined]
    # tx1 comes next due to lowest priority fallback
    assert math.isinf(queue._normal_priority_queues[peer3].get_top_tx_priority())
    entry = await queue.pop()
    assert entry.index == 0  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_normal_queue_deficit_round_robin(seeded_random: random.Random) -> None:
    """
    Covers the heap-based deficit round robin behavior of the normal
    transaction queues where we cycle through peers and pick their top
    transactions by fast forwarding the global accumulated deficit when peers
    can't afford their top transactions.
    This also covers the case where a peer's top transaction does not advertise
    cost, so that falls back to `max_tx_clvm_cost`.
    This also covers when peers join the queue after some deficit has already
    accumulated globally.
    This also covers tie-breaking on peer ID when two peers have the same
    required global deficit.
    Finally this also covers cleanup of peers that run out of transactions.
    """

    def get_local_deficit_counter(queue: TransactionQueue, peer_id: bytes32) -> int | None:
        peer_txs_info = queue._normal_priority_queues.get(peer_id)
        return peer_txs_info.deficit_counter if peer_txs_info is not None else None

    def get_effective_deficit(queue: TransactionQueue, peer_id: bytes32) -> int | None:
        local_deficit_counter = get_local_deficit_counter(queue, peer_id)
        if local_deficit_counter is None:
            return None
        return local_deficit_counter + queue._drr_heap.global_accumulated_deficit

    test_max_tx_clvm_cost = uint64(20)
    queue = TransactionQueue(42, log, test_max_tx_clvm_cost)
    [peer1, peer2, peer3, peer4, peer5] = sorted([bytes32.random(seeded_random) for _ in range(5)], reverse=True)
    test_fee = uint64(42)
    # We give this one the highest cost
    tx1_name = bytes32.random(seeded_random)
    tx1 = get_transaction_queue_entry(peer1, 0, {peer1: PeerWithTx(str(peer1), test_fee, uint64(15))}, tx1_name)
    queue.put(tx1, peer1)
    # And this one the lowest cost
    tx2_name = bytes32.random(seeded_random)
    tx2 = get_transaction_queue_entry(peer2, 1, {peer2: PeerWithTx(str(peer2), test_fee, uint64(5))}, tx2_name)
    queue.put(tx2, peer2)
    # And this one a cost in between
    tx3_name = bytes32.random(seeded_random)
    tx3 = get_transaction_queue_entry(peer3, 2, {peer3: PeerWithTx(str(peer3), test_fee, uint64(10))}, tx3_name)
    queue.put(tx3, peer3)
    # This one has no cost information so its top transaction's advertised cost
    # falls back to `test_max_tx_clvm_cost`.
    tx4_name = bytes32.random(seeded_random)
    tx4 = get_transaction_queue_entry(peer4, 3, {}, tx4_name)
    queue.put(tx4, peer4)
    # Check the initial state
    assert queue._drr_heap.global_accumulated_deficit == 0
    for peer_id in [peer1, peer2, peer3, peer4]:
        assert get_local_deficit_counter(queue, peer_id) == 0
        assert get_effective_deficit(queue, peer_id) == 0
    # When we try to pop the top transaction, its peer (peer2) can't afford to
    # do that so we fast forward the global accumulated deficit to what's
    # required (5) and tx2 goes through.
    entry = await queue.pop()
    assert entry.spend_name == tx2_name
    assert peer2 not in queue._normal_priority_queues
    assert queue._drr_heap.global_accumulated_deficit == 5
    assert get_local_deficit_counter(queue, peer2) is None
    assert get_effective_deficit(queue, peer2) is None
    for peer_id in [peer1, peer3, peer4]:
        assert get_local_deficit_counter(queue, peer_id) == 0
        assert get_effective_deficit(queue, peer_id) == 5
    # Now top transaction's peer (peer3) can't afford it, so we fast forward
    # the global accumulated deficit to what's required (10) and tx3 pops.
    entry = await queue.pop()
    assert entry.spend_name == tx3_name
    assert peer3 not in queue._normal_priority_queues
    assert queue._drr_heap.global_accumulated_deficit == 10
    assert get_local_deficit_counter(queue, peer3) is None
    assert get_effective_deficit(queue, peer3) is None
    for peer_id in [peer1, peer4]:
        assert get_local_deficit_counter(queue, peer_id) == 0
        assert get_effective_deficit(queue, peer_id) == 10
    # Now top transaction's peer (peer1) can't afford it, so we fast forward
    # the global accumulated deficit to what's required (15) and tx1 pops.
    entry = await queue.pop()
    assert entry.spend_name == tx1_name
    assert peer1 not in queue._normal_priority_queues
    assert queue._drr_heap.global_accumulated_deficit == 15
    assert get_local_deficit_counter(queue, peer1) is None
    assert get_effective_deficit(queue, peer1) is None
    assert get_local_deficit_counter(queue, peer4) == 0
    assert get_effective_deficit(queue, peer4) == 15
    # Peer5 didn't have any transactions before and it's about to receive one
    # now. It gets an effective deficit of 0 through a deficit counter of -15.
    # We set it to tie with peer4 whose top transaction's cost is 20 by giving
    # tx5 a cost of 5.
    assert peer5 not in queue._normal_priority_queues
    tx5_name = bytes32.random(seeded_random)
    tx5 = get_transaction_queue_entry(peer5, 4, {peer5: PeerWithTx(str(peer5), test_fee, uint64(5))}, tx5_name)
    queue.put(tx5, peer5)
    assert peer5 in queue._normal_priority_queues
    assert queue._drr_heap.global_accumulated_deficit == 15
    assert get_local_deficit_counter(queue, peer5) == -queue._drr_heap.global_accumulated_deficit
    assert get_effective_deficit(queue, peer5) == 0
    # Now required global deficit is 20 which both peer4 and peer5 have but we
    # tie-break on `peer_id` and peer5 goes first. We fast forward the global
    # accumulated deficit (from 15 to 20) and tx5 pops.
    assert peer5 < peer4
    entry = await queue.pop()
    assert entry.spend_name == tx5_name
    assert peer5 not in queue._normal_priority_queues
    assert queue._drr_heap.global_accumulated_deficit == 20
    assert get_local_deficit_counter(queue, peer5) is None
    assert get_effective_deficit(queue, peer5) is None
    assert get_local_deficit_counter(queue, peer4) == 0
    assert get_effective_deficit(queue, peer4) == 20
    # Finally peer4 gets its tx4 through
    entry = await queue.pop()
    assert entry.spend_name == tx4_name
    assert queue._drr_heap.global_accumulated_deficit == 20
    for peer_id in [peer1, peer2, peer3, peer4, peer5]:
        assert peer_id not in queue._normal_priority_queues
        assert get_local_deficit_counter(queue, peer_id) is None
        assert get_effective_deficit(queue, peer_id) is None
