from __future__ import annotations

import asyncio
import dataclasses
import heapq
import logging
from dataclasses import dataclass, field
from queue import PriorityQueue, SimpleQueue
from typing import ClassVar, Generic, TypeVar

from chia_rs import SpendBundle
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.server.ws_connection import WSChiaConnection
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err

T = TypeVar("T")


class TransactionQueueFull(Exception):
    pass


class ValuedEventSentinel:
    pass


@dataclasses.dataclass
class ValuedEvent(Generic[T]):
    _value_sentinel: ClassVar[ValuedEventSentinel] = ValuedEventSentinel()

    _event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    _value: ValuedEventSentinel | T = _value_sentinel

    def set(self, value: T) -> None:
        if not isinstance(self._value, ValuedEventSentinel):
            raise Exception("Value already set")
        self._value = value
        self._event.set()

    async def wait(self) -> T:
        await self._event.wait()
        if isinstance(self._value, ValuedEventSentinel):
            raise Exception("Value not set despite event being set")
        return self._value


@dataclasses.dataclass(frozen=True)
class PeerWithTx:
    peer_host: str
    advertised_fee: uint64
    advertised_cost: uint64


@dataclass(frozen=True, order=True)
class TransactionQueueEntry:
    """
    A transaction received from peer. This is put into a queue, and not yet in the mempool.
    """

    transaction: SpendBundle = field(compare=False)
    transaction_bytes: bytes | None = field(compare=False)
    spend_name: bytes32
    peer: WSChiaConnection | None = field(compare=False)
    test: bool = field(compare=False)
    # IDs of peers that advertised this transaction via new_transaction, along
    # with their hostname, fee and cost.
    peers_with_tx: dict[bytes32, PeerWithTx] = field(default_factory=dict, compare=False)
    done: ValuedEvent[tuple[MempoolInclusionStatus, Err | None]] = field(
        default_factory=ValuedEvent,
        compare=False,
    )


@dataclass
class NormalPriorityQueue:
    # Peer's priority queue of the form (negative fee per cost, entry).
    # We sort like this because PriorityQueue returns lowest first.
    priority_queue: PriorityQueue[tuple[float, TransactionQueueEntry]]
    # Peer's local deficit relative to the global accumulated deficit, with the
    # effective deficit being the sum of both. The unit here is in CLVM cost.
    deficit_counter: int

    def empty(self) -> bool:
        return self.priority_queue.empty()

    def get_top_tx_priority(self) -> float:
        try:
            top_tx_priority, _ = self.priority_queue.queue[0]
        except IndexError:
            return float("inf")
        return top_tx_priority

    def get_top_tx_id_and_cost(self, peer_id: bytes32, default_cost: uint64) -> tuple[bytes32, uint64] | None:
        try:
            _, entry = self.priority_queue.queue[0]
        except IndexError:
            return None
        top_tx_info = entry.peers_with_tx.get(peer_id)
        top_tx_cost = top_tx_info.advertised_cost if top_tx_info is not None else default_cost
        return entry.spend_name, top_tx_cost


@dataclass
class DrrHeap:
    max_tx_clvm_cost: uint64
    # (required_global_deficit, peer_id, cost_of_top_tx, top_tx_name)
    # NOTE: `required_global_deficit` is the required global accumulated
    # deficit that allows the peer to afford this transaction.
    heap: list[tuple[int, bytes32, uint64, bytes32]] = field(default_factory=list)
    # Map of peer ID to its top transaction's name
    peer_top_tx_name: dict[bytes32, bytes32] = field(default_factory=dict)
    global_accumulated_deficit: int = 0

    def push(
        self, required_global_deficit: int, peer_id: bytes32, cost_of_top_tx: uint64, top_tx_name: bytes32
    ) -> None:
        self.peer_top_tx_name[peer_id] = top_tx_name
        heapq.heappush(self.heap, (required_global_deficit, peer_id, cost_of_top_tx, top_tx_name))

    def pop(self) -> tuple[bytes32, uint64] | None:
        while len(self.heap) > 0:
            required_global_deficit, peer_id, cost_of_top_tx, top_tx_name = heapq.heappop(self.heap)
            current_top_tx_name = self.peer_top_tx_name.get(peer_id)
            if current_top_tx_name is None or current_top_tx_name != top_tx_name:
                continue
            # If this peer can't afford this top transaction, fast-forward
            # global deficit.
            self.global_accumulated_deficit = max(self.global_accumulated_deficit, required_global_deficit)
            return peer_id, cost_of_top_tx
        return None

    def clear(self) -> None:
        self.heap = []
        self.peer_top_tx_name = {}
        self.global_accumulated_deficit = 0

    def sort_peer(self, peer_id: bytes32, peer_queue: NormalPriorityQueue) -> None:
        """
        Inserts the peer's top transaction into the deficit round robin heap.
        """
        top_tx_id_and_cost = peer_queue.get_top_tx_id_and_cost(peer_id, self.max_tx_clvm_cost)
        if top_tx_id_and_cost is None:
            return
        top_tx_name, cost_of_top_tx = top_tx_id_and_cost
        # We want the peer with the highest surplus (deficit - cost) to go
        # first, but heapq returns lowest first, so we invert it and we get
        # essentially (cost - deficit) which is the required global accumulated
        # deficit.
        required_global_deficit = int(cost_of_top_tx) - peer_queue.deficit_counter
        self.push(required_global_deficit, peer_id, cost_of_top_tx, top_tx_name)


@dataclass
class TransactionQueue:
    """
    This class replaces one queue by using a high priority queue for local transactions and separate queues for peers.
    Local transactions are processed first.
    Then the next transaction is selected using an adapted version of the deficit round robin algorithm.
    This decreases the effects of one peer spamming your node with transactions.
    """

    _queue_length: asyncio.Semaphore
    _normal_priority_queues: dict[bytes32, NormalPriorityQueue]
    _high_priority_queue: SimpleQueue[TransactionQueueEntry]
    peer_size_limit: int
    log: logging.Logger
    _drr_heap: DrrHeap

    def __init__(self, peer_size_limit: int, log: logging.Logger, max_tx_clvm_cost: uint64) -> None:
        self._queue_length = asyncio.Semaphore(0)  # default is 1
        self._normal_priority_queues = {}
        self._high_priority_queue = SimpleQueue()  # we don't limit the number of high priority transactions
        self.peer_size_limit = peer_size_limit
        self.log = log
        self._drr_heap = DrrHeap(max_tx_clvm_cost)

    def put(self, tx: TransactionQueueEntry, peer_id: bytes32 | None, high_priority: bool = False) -> None:
        if peer_id is None or high_priority:  # when it's local there is no peer_id.
            self._high_priority_queue.put(tx)
            self._queue_length.release()
            return
        if len(self._normal_priority_queues) == 0:
            self._drr_heap.clear()
        peer_queue = self._normal_priority_queues.get(peer_id)
        if peer_queue is None:
            # Start with effectively 0 deficit (sum of this local deficit
            # and the global accumulated one).
            deficit_counter = -self._drr_heap.global_accumulated_deficit
            peer_queue = NormalPriorityQueue(priority_queue=PriorityQueue(), deficit_counter=deficit_counter)
            self._normal_priority_queues[peer_id] = peer_queue
        if peer_queue.priority_queue.qsize() >= self.peer_size_limit:
            self.log.warning(f"Transaction queue full for peer {peer_id}")
            raise TransactionQueueFull(f"Transaction queue full for peer {peer_id}")
        was_priority_queue_empty = peer_queue.priority_queue.empty()
        top_tx_priority_before = peer_queue.get_top_tx_priority()
        tx_info = tx.peers_with_tx.get(peer_id)
        if tx_info is not None and tx_info.advertised_cost > 0:
            fpc = tx_info.advertised_fee / tx_info.advertised_cost
            # PriorityQueue returns lowest first so we invert
            priority = -fpc
        else:
            # This peer didn't advertise cost and fee information for
            # this transaction (it sent a `RespondTransaction` message
            # instead of a `NewTransaction` one).
            priority = float("inf")
        peer_queue.priority_queue.put((priority, tx))
        # If the peer queue was empty before or its top transaction has
        # changed, we need to sort again.
        if was_priority_queue_empty or priority < top_tx_priority_before:
            self._drr_heap.sort_peer(peer_id, peer_queue)
        self._queue_length.release()  # increment semaphore to indicate that we have a new item in the queue

    async def pop(self) -> TransactionQueueEntry:
        await self._queue_length.acquire()
        if not self._high_priority_queue.empty():
            return self._high_priority_queue.get()
        while True:
            drr_heap_entry = self._drr_heap.pop()
            if drr_heap_entry is None:
                continue
            peer_id, cost_of_top_tx = drr_heap_entry
            peer_txs_info = self._normal_priority_queues.get(peer_id)
            if peer_txs_info is None:
                continue
            if peer_txs_info.empty():
                self._normal_priority_queues.pop(peer_id, None)
                continue
            _, entry = peer_txs_info.priority_queue.get()
            peer_txs_info.deficit_counter -= int(cost_of_top_tx)
            # Cleanup/Resort based on whether we have remaining transactions
            if peer_txs_info.empty():
                self._normal_priority_queues.pop(peer_id, None)
            else:
                self._drr_heap.sort_peer(peer_id, peer_txs_info)
            return entry
