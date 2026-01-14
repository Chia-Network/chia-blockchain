from __future__ import annotations

import asyncio
import dataclasses
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
class PeerTransactionsQueue:
    # Peer's priority queue of the form (negative fee per cost, entry).
    # We sort like this because PriorityQueue returns lowest first.
    priority_queue: PriorityQueue[tuple[float, TransactionQueueEntry]] = field(default_factory=PriorityQueue)
    # Peer's deficit in the context of deficit round robin algorithm. The unit
    # here is in CLVM cost.
    deficit: int = field(default=0, init=False)


@dataclass
class TransactionQueue:
    """
    This class replaces one queue by using a high priority queue for local transactions and separate queues for peers.
    Local transactions are processed first.
    Then the next transaction is taken from the next non-empty queue after the last processed queue. (round-robin)
    This decreases the effects of one peer spamming your node with transactions.
    """

    _list_cursor: int  # this is which index
    _queue_length: asyncio.Semaphore
    _index_to_peer_map: list[bytes32]
    _peers_transactions_queues: dict[bytes32, PeerTransactionsQueue]
    _high_priority_queue: SimpleQueue[TransactionQueueEntry]
    peer_size_limit: int
    log: logging.Logger
    # Fallback cost for transactions without cost information
    _max_tx_clvm_cost: uint64
    # Each 100 pops we do a cleanup of empty peer queues
    _cleanup_counter: int

    def __init__(self, peer_size_limit: int, log: logging.Logger, *, max_tx_clvm_cost: uint64) -> None:
        self._list_cursor = 0
        self._queue_length = asyncio.Semaphore(0)  # default is 1
        self._index_to_peer_map = []
        self._peers_transactions_queues = {}
        self._high_priority_queue = SimpleQueue()  # we don't limit the number of high priority transactions
        self.peer_size_limit = peer_size_limit
        self.log = log
        self._max_tx_clvm_cost = max_tx_clvm_cost
        self._cleanup_counter = 0

    def put(self, tx: TransactionQueueEntry, peer_id: bytes32 | None, high_priority: bool = False) -> None:
        if peer_id is None or high_priority:  # when it's local there is no peer_id.
            self._high_priority_queue.put(tx)
            self._queue_length.release()
            return
        peer_queue = self._peers_transactions_queues.get(peer_id)
        if peer_queue is None:
            peer_queue = PeerTransactionsQueue()
            self._peers_transactions_queues[peer_id] = peer_queue
            self._index_to_peer_map.append(peer_id)
        if self._peers_transactions_queues[peer_id].priority_queue.qsize() >= self.peer_size_limit:
            self.log.warning(f"Transaction queue full for peer {peer_id}")
            raise TransactionQueueFull(f"Transaction queue full for peer {peer_id}")
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
        self._queue_length.release()  # increment semaphore to indicate that we have a new item in the queue

    def _cleanup_peer_queues(self) -> None:
        """
        Removes empty peer queues and updates the cursor accordingly.
        """
        new_peer_map = []
        for idx, peer_id in enumerate(self._index_to_peer_map):
            if self._peers_transactions_queues[peer_id].priority_queue.empty():
                self._peers_transactions_queues.pop(peer_id, None)
                if idx < self._list_cursor:
                    self._list_cursor -= 1
            else:
                new_peer_map.append(peer_id)
        self._index_to_peer_map = new_peer_map
        if self._list_cursor >= len(self._index_to_peer_map):
            self._list_cursor = 0

    async def pop(self) -> TransactionQueueEntry:
        await self._queue_length.acquire()
        if not self._high_priority_queue.empty():
            return self._high_priority_queue.get()
        while True:
            # Map of peer ID to its top transaction's advertised cost. We want
            # to service transactions fairly between peers, based on cost, so
            # we need to find the lowest cost transaction among the top ones.
            top_txs_advertised_costs: dict[bytes32, uint64] = {}
            # Let's see if a peer can afford to send its top transaction
            num_peers = len(self._index_to_peer_map)
            assert num_peers != 0
            start = self._list_cursor
            for offset in range(num_peers):
                peer_index = (start + offset) % num_peers
                peer_id = self._index_to_peer_map[peer_index]
                peer_queue = self._peers_transactions_queues[peer_id]
                if peer_queue.priority_queue.empty():
                    continue
                # There is no peek method so we access the internal `queue`
                _, entry = peer_queue.priority_queue.queue[0]
                tx_info = entry.peers_with_tx.get(peer_id)
                # If we don't know the cost information for this transaction
                # we fallback to the highest cost.
                if tx_info is not None:
                    # At this point we have no transactions with zero cost
                    assert tx_info.advertised_cost > 0
                    top_tx_advertised_cost = tx_info.advertised_cost
                else:
                    top_tx_advertised_cost = self._max_tx_clvm_cost
                top_txs_advertised_costs[peer_id] = top_tx_advertised_cost
                if peer_queue.deficit >= top_tx_advertised_cost:
                    # This peer can afford its top transaction
                    _, entry = peer_queue.priority_queue.get()
                    peer_queue.deficit -= top_tx_advertised_cost
                    if peer_queue.priority_queue.empty():
                        peer_queue.deficit = 0
                    # Let's advance the cursor to the next peer
                    self._list_cursor = (peer_index + 1) % num_peers
                    # See if we need to perform the periodic cleanup
                    self._cleanup_counter = (self._cleanup_counter + 1) % 100
                    if self._cleanup_counter == 0:
                        self._cleanup_peer_queues()
                    return entry
            # None of the peers could afford to send their top transactions, so
            # let's add the lowest cost among transactions to all the deficit
            # counters for the next iteration.
            assert len(top_txs_advertised_costs) != 0
            lowest_cost_among_txs = min(top_txs_advertised_costs.values())
            for peer_id in top_txs_advertised_costs:
                self._peers_transactions_queues[peer_id].deficit += lowest_cost_among_txs
