from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.transaction_queue_entry import TransactionQueueEntry


@dataclass
class TransactionQueue:
    """
    This class replaces a simple queue, with a high priority queue for local transactions, and a separate queue for each peer.
    After local transactions are processed, the next transaction is taken from the next non-empty queue after the last processed queue. (round-robin)
    This decreases the effects of one peer spamming your node with transactions.
    """

    _list_iterator: int
    _queue_length: asyncio.Semaphore
    _index_to_peer_map: List[bytes32]
    _queue_dict: Dict[bytes32, asyncio.Queue[TransactionQueueEntry]]
    _high_priority_queue: asyncio.Queue[TransactionQueueEntry]
    peer_size_limit: int
    log: logging.Logger

    def __init__(self, peer_size_limit: int, log: logging.Logger) -> None:
        self._list_iterator = 0
        self._queue_length = asyncio.Semaphore(0)  # default is 1
        self._index_to_peer_map = []
        self._queue_dict = {}
        self._high_priority_queue = asyncio.Queue(peer_size_limit)
        self.peer_size_limit = peer_size_limit
        self.log = log

    async def put(self, tx: TransactionQueueEntry, high_priority: bool = False) -> None:
        if tx.peer is None or high_priority:  # when it's local there is no peer.
            await self._high_priority_queue.put(tx)
        else:
            if tx.peer not in self._queue_dict:
                self._queue_dict[tx.peer.peer_node_id] = asyncio.Queue(self.peer_size_limit)
                self._index_to_peer_map.append(tx.peer.peer_node_id)
            try:
                self._queue_dict[tx.peer.peer_node_id].put_nowait(tx)
            except asyncio.QueueFull:
                self.log.warning(f"Transaction queue full for peer {tx.peer.peer_node_id}")
                return
        self._queue_length.release()  # increment semaphore to indicate that we have a new item in the queue

    async def pop(self) -> TransactionQueueEntry:
        await self._queue_length.acquire()
        list_length = len(self._index_to_peer_map)
        if not self._high_priority_queue.empty():
            return self._high_priority_queue.get_nowait()
        peer_id = self._index_to_peer_map[self._list_iterator]
        while True:
            if not self._queue_dict[peer_id].empty():
                return self._queue_dict[peer_id].get_nowait()
            self._list_iterator += 1
            peer_id = self._index_to_peer_map[self._list_iterator]
            if self._list_iterator > list_length:
                # reset iterator
                self._list_iterator = 0

    async def clean_up_queue(self) -> None:
        while True:
            await asyncio.sleep(600)
            for peer_id in self._queue_dict:
                if self._queue_dict[peer_id].empty():
                    self._queue_dict.pop(peer_id)
                    self._index_to_peer_map.remove(peer_id)
            if self._list_iterator > len(self._index_to_peer_map):
                self._list_iterator = 0
