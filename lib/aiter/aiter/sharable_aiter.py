import asyncio


class sharable_aiter:
    """
    Not all iterators can have multiple consumers. For example, asynchronous
    generators don't allow it. But if you wrap it with one of these,
    you'll be okay.
    """

    def __init__(self, aiter):
        self._opened_aiter = aiter.__aiter__()
        self._semaphore = asyncio.Semaphore()

    def __aiter__(self):
        return self

    async def __anext__(self):
        async with self._semaphore:
            return await self._opened_aiter.__anext__()
