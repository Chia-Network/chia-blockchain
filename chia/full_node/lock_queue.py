import asyncio


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
        self._release_event = asyncio.Event()

    async def put(self, priority: int, callback):
        await self._task_queue.put((priority, FuncWrapper(callback)))

    async def acquire(self):
        await self._inner_lock.acquire()

    def release(self):
        self._inner_lock.release()
        self._release_event.set()

    async def _run(self):
        while not self._stopped:
            priority, callback = await self._task_queue.get()
            self._release_event = asyncio.Event()
            await self.acquire()
            await callback.f()
            await self._release_event.wait()

    def close(self):
        self._stopped = True
        self._run_task.cancel()


class LockClient:
    def __init__(self, priority: int, queue: LockQueue):
        self._priority = priority
        self._queue = queue

    async def __aenter__(
        self,
    ):
        called: asyncio.Event = asyncio.Event()

        async def callback():
            nonlocal called
            called.set()

        await self._queue.put(self._priority, callback)

        await called.wait()

    async def __aexit__(self, exc_type, exc, tb):
        self._queue.release()
