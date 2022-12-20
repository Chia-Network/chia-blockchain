from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from queue import SimpleQueue
from typing import Dict, List, Optional

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.transaction_queue_entry import TransactionQueueEntry


class TransactionQueueFull(Exception):
    pass


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
    _index_to_peer_map: List[bytes32]
    _queue_dict: Dict[bytes32, SimpleQueue[TransactionQueueEntry]]
    _high_priority_queue: SimpleQueue[TransactionQueueEntry]
    peer_size_limit: int
    log: logging.Logger

    def __init__(self, peer_size_limit: int, log: logging.Logger) -> None:
        self._list_cursor = 0
        self._queue_length = asyncio.Semaphore(0)  # default is 1
        self._index_to_peer_map = []
        self._queue_dict = {}
        self._high_priority_queue = SimpleQueue()  # we don't limit the number of high priority transactions
        self.peer_size_limit = peer_size_limit
        self.log = log

    async def put(self, tx: TransactionQueueEntry, peer_id: Optional[bytes32], high_priority: bool = False) -> None:
        if peer_id is None or high_priority:  # when it's local there is no peer_id.
            self._high_priority_queue.put(tx)
        else:
            if peer_id not in self._queue_dict:
                self._queue_dict[peer_id] = SimpleQueue()
                self._index_to_peer_map.append(peer_id)
            if self._queue_dict[peer_id].qsize() < self.peer_size_limit:
                self._queue_dict[peer_id].put(tx)
            else:
                self.log.warning(f"Transaction queue full for peer {peer_id}")
                raise TransactionQueueFull(f"Transaction queue full for peer {peer_id}")
        self._queue_length.release()  # increment semaphore to indicate that we have a new item in the queue

    async def pop(self) -> TransactionQueueEntry:
        await self._queue_length.acquire()
        if not self._high_priority_queue.empty():
            return self._high_priority_queue.get()
        result: Optional[TransactionQueueEntry] = None
        while True:
            peer_queue = self._queue_dict[self._index_to_peer_map[self._list_cursor]]
            if not peer_queue.empty():
                result = peer_queue.get()
            self._list_cursor += 1
            if self._list_cursor > len(self._index_to_peer_map) - 1:
                # reset iterator
                self._list_cursor = 0
                new_peer_map = []
                for peer_id in self._index_to_peer_map:
                    if self._queue_dict[peer_id].empty():
                        self._queue_dict.pop(peer_id)
                    else:
                        new_peer_map.append(peer_id)
                self._index_to_peer_map = new_peer_map
            if result is not None:
                return result
