import asyncio


class stoppable_aiter:
    """
    A wrapper around an iterator that supports a manual shut-off.
    """

    def __init__(self, aiter):
        self._open_aiter = aiter.__aiter__()
        self._is_stopping = False
        self._semaphore = asyncio.Semaphore()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._is_stopping:
            raise StopAsyncIteration
        async with self._semaphore:
            return await self._open_aiter.__anext__()

    def stop(self):
        self._is_stopping = True
