import asyncio


class push_aiter:
    """
    An asynchronous iterator based on a linked-list.
    Data goes in the head via "push".
    Allows peeking to determine how many elements are ready.

    This is functionally similar to an :class:`async.Queue <async.Queue>`
    object. It creates an aiter that you can `push` items into.
    Unlike a `Queue` object, you can also invoke :py:func:`stop <stop>`, which will
    raise a `StopAsyncIteration` on the listener's side, allowing for a
    clean exit.

    You'd use this when you want to "turn around" execution, ie. have
    a task that is occasionally invoked (like a hardware interrupt)
    to produce a new event for an aiter.
    """
    def __init__(self):
        self._head = self._tail = asyncio.Future()

    def push(self, *items):
        """
        Accept one or more item and push them to the end of the
        aiter's queue.
        """
        if self._head.cancelled():
            raise ValueError("%s closed" % self)
        for item in items:
            f = asyncio.Future()
            self._head.set_result((item, f))
            self._head = f

    def stop(self):
        """
        Raise a `StopAsyncIteration` exception on the listener side
        once no more already-queued elements are pending.
        """
        self._head.cancel()

    async def __aiter__(self):
        try:
            while True:
                _, self._tail = await self._tail
                yield _
        except asyncio.CancelledError:
            pass

    def available_iter(self):
        """
        Return a *synchronous* iterator of elements that are immediately
        available to be consumed without waiting for a task switch.
        """
        tail = self._tail
        try:
            while tail.done():
                _, tail = tail.result()
                yield _
        except asyncio.CancelledError:
            pass

    def is_stopped(self):
        """
        Return a boolean indicating whether or not :py:func:`stop <stop>`
        has been called. Additional elements may still be available.

        :return: whether or not the aiter has been stopped
        :rtype: bool
        """
        return self._tail.cancelled()

    def is_item_available(self):
        """
        Return a boolean indicating whether or not an element is available without
        blocking for a task switch.

        :return: whether or not the aiter has been stopped
        :rtype: bool
        """
        return self.is_len_at_least(1)

    def is_len_at_least(self, n):
        """
        Return a boolean indicating whether or not `n` elements are available without
        blocking for a task switch.

        :type n: int
        :param n: count of items

        :return: True iff n items are available
        :rtype: bool
        """
        for _, item in enumerate(self.available_iter()):
            if _+1 >= n:
                return True
        return False

    def __len__(self):
        """
        :return: number of items immediately available withouth blocking
        :rtype: int
        """

        return sum(1 for _ in self.available_iter())
