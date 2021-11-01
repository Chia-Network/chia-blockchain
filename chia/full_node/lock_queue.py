import asyncio
from typing import Optional


class FuncWrapper:
    def __init__(self, f):
        self.f = f

    def __lt__(self, other):
        return str(self.f) < str(other)

    def __le__(self, other):
        return str(self.f) <= str(other)

    def __gt__(self, other):
        return str(self.f) > str(other)

    def __ge__(self, other):
        return str(self.f) >= str(other)


class LockQueue:
    def __init__(self, inner_lock: asyncio.Lock):
        self._inner_lock: asyncio.Lock = inner_lock
        self._task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._stopped = False
        self._run_task = asyncio.create_task(self._run())

    async def put(self, priority: int, callback):
        await self._task_queue.put((priority, FuncWrapper(callback)))

    async def acquire(self):
        await self._inner_lock.acquire()

    def release(self):
        self._inner_lock.release()

    async def _run(self):
        while not self._stopped:
            priority, callback = await self._task_queue.get()
            await callback.f()
            while self._inner_lock.locked():
                await asyncio.sleep(0.001)

    def close(self):
        self._stopped = True
        self._run_task.cancel()


class TooManyLockClients(Exception):
    pass


class LockClient:
    def __init__(self, priority: int, queue: LockQueue, max_clients: Optional[int]=None):
        self._priority = priority
        self._queue = queue
        self._max_clients = max_clients
        self._curr_clients = 0

    async def __aenter__(
        self,
    ):
        called: bool = False
        if self._max_clients is not None and self._curr_clients >= self._max_clients:
            raise TooManyLockClients()
        self._curr_clients += 1

        async def callback():
            await self._queue.acquire()
            nonlocal called
            called = True

        await self._queue.put(self._priority, callback)

        while not called:
            await asyncio.sleep(0.001)

    async def __aexit__(self, exc_type, exc, tb):
        self._queue.release()
        self._curr_clients -= 1
