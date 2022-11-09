import asyncio
from dataclasses import dataclass
from typing import List, Dict, Optional

from chia.server.ws_connection import WSChiaConnection
from chia.types.transaction_queue_entry import TransactionQueueEntry


@dataclass
class TransactionQueue:
    _list_iterator: int
    _queue_length: asyncio.Semaphore
    _index_to_peer_map: List[WSChiaConnection]
    _queue_dict: Dict[WSChiaConnection, asyncio.Queue[TransactionQueueEntry]]
    _high_priority_queue: asyncio.Queue[TransactionQueueEntry]
    _max_size: int

    def __init__(self, max_size: int):
        self._list_iterator = 0
        self._queue_length = asyncio.Semaphore()
        self._index_to_peer_map = []
        self._queue_dict = {}
        self._high_priority_queue = asyncio.Queue(max_size)
        self._max_size = max_size

    def qsize(self) -> int:
        return self._queue_length._value

    def full(self, peer: Optional[WSChiaConnection] = None) -> bool:
        return self.qsize() == self._max_size or (peer is not None and not self._queue_dict[peer].full())

    def empty(self) -> bool:
        return self.qsize() == 0

    async def put(self, tx: TransactionQueueEntry, high_priority: bool = False) -> None:
        if tx.peer is None or high_priority:  # when it's local there is no peer.
            await self._high_priority_queue.put(tx)
        else:
            if tx.peer not in self._queue_dict:
                self._queue_dict[tx.peer] = asyncio.Queue(1000)
                self._index_to_peer_map.append(tx.peer)
            await self._queue_dict[tx.peer].put(tx)
        self._queue_length.release()  # increment semaphore to indicate that we have a new item in the queue

    async def get(self) -> TransactionQueueEntry:
        await self._queue_length.acquire()
        list_length = len(self._index_to_peer_map)
        if self._high_priority_queue.qsize() > 0:
            return await self._high_priority_queue.get()
        while True:
            peer = self._index_to_peer_map[self._list_iterator]
            self._list_iterator += 1
            if not self._queue_dict[peer].empty():
                return await self._queue_dict[peer].get()
            elif self._list_iterator > list_length:
                # reset iterator
                self._list_iterator = 0

    async def clean_up_queue(self) -> None:
        while True:
            await asyncio.sleep(600)
            for peer in self._queue_dict:
                if self._queue_dict[peer].empty() or peer.closed:
                    self._queue_dict.pop(peer)
                    self._index_to_peer_map.remove(peer)
