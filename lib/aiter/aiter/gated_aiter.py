import asyncio

from .azip import azip
from .active_aiter import active_aiter
from .map_filter_aiter import map_filter_aiter
from .push_aiter import push_aiter


class gated_aiter:
    """
    Returns an aiter that you can "push" integer values into.
    When a number is pushed, that many items are allowed out through the gate.

    This is kind of like a discrete version of an electronic transistor.

    :type aiter: aiter
    :param aiter: an async iterator

    :return: an async iterator yielding the same values as the original aiter
    :rtype: :class:`aiter.gated_aiter <gated_aiter>`
    """
    def __init__(self, aiter):
        self._gate = push_aiter()
        self._open_aiter = active_aiter(azip(aiter, map_filter_aiter(range, self._gate))).__aiter__()
        self._semaphore = asyncio.Semaphore()

    def __aiter__(self):
        return self

    async def __anext__(self):
        async with self._semaphore:
            return (await self._open_aiter.__anext__())[0]

    def push(self, count):
        """
        Note that several additional items are allowed through the gated_aiter.

        :type count: int
        :param count: the number of items that can be allowed out the aiter. These are cumulative.
        """
        if not self._gate.is_stopped():
            self._gate.push(count)

    def stop(self):
        """
        After the previously authorized items (from `push`) are pulled out the aiter, the aiter will exit.
        """
        self._gate.stop()
