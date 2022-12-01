from __future__ import annotations

import asyncio
import dataclasses
import logging
import traceback
from types import TracebackType
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, order=True)
class PrioritizedCallable:
    priority: int
    af: Callable[[], Awaitable[object]] = dataclasses.field(compare=False)


class LockQueue:
    """
    The purpose of this class is to be able to control access to a lock, and give priority to certain clients
    (LockClients). To use it, create a lock and clients:
    ```
    my_lock = LockQueue(asyncio.Lock())
    client_a = LockClient(0, my_lock)
    client_b = LockClient(1, my_lock)

    async with client_a:
       ...
    ```

    The clients can be used like normal async locks, but the higher priority (lower number) will always go first.
    Must be created under an asyncio running loop, and close and await_closed should be called.
    """

    def __init__(self, inner_lock: asyncio.Lock):
        self._inner_lock: asyncio.Lock = inner_lock
        self._task_queue: asyncio.PriorityQueue[PrioritizedCallable] = asyncio.PriorityQueue()
        self._run_task = asyncio.create_task(self._run())
        self._release_event = asyncio.Event()

    async def put(self, priority: int, callback: Callable[[], Awaitable[object]]) -> None:
        await self._task_queue.put(PrioritizedCallable(priority=priority, af=callback))

    async def acquire(self) -> None:
        await self._inner_lock.acquire()

    def release(self) -> None:
        self._inner_lock.release()
        self._release_event.set()

    async def _run(self) -> None:
        try:
            while True:
                prioritized_callback = await self._task_queue.get()
                self._release_event = asyncio.Event()
                await self.acquire()
                await prioritized_callback.af()
                await self._release_event.wait()
        except asyncio.CancelledError:
            error_stack = traceback.format_exc()
            log.debug(f"LockQueue._run() cancelled: {error_stack}")

    def close(self) -> None:
        self._run_task.cancel()

    async def await_closed(self) -> None:
        await self._run_task


class LockClient:
    def __init__(self, priority: int, queue: LockQueue):
        self._priority = priority
        self._queue = queue

    async def __aenter__(self) -> None:
        called: asyncio.Event = asyncio.Event()

        # Use a parameter default to avoid a closure
        async def callback(called_inner: asyncio.Event = called) -> None:
            called_inner.set()

        await self._queue.put(priority=self._priority, callback=callback)
        await called.wait()

    async def __aexit__(
        self, typ: type[BaseException] | None, value: BaseException | None, traceback: TracebackType | None
    ) -> bool | None:
        self._queue.release()
        return None
