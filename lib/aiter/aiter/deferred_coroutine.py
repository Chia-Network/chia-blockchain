import asyncio


class deferred_coroutine:
    """
    This class allows a co-routine to be invoked later by one of
    potentially many tasks, and only "borrow" the execution from
    the first task that wants the result.

    Although lambda_coroutine can technically be any awaitable, the typical use
    case is a 0-argument function that returns a coroutine, since it's going to be
    await'ed.

    :type lambda_coroutine: function
    :param lambda_coroutine: a 0-argument function returning an awaitable (usually a coroutine)
    """
    def __init__(self, lambda_coroutine):
        self._next_future = asyncio.Future()
        self._active_invoked = False
        self._lambda_coroutine = lambda_coroutine

    async def wait(self, is_active=True):
        """
        The first time this is invoked with is_active True, the awaitable returned from
        lambda_coroutine is awaited. Then the awaited value is returned.

        Subsequent calls return the awaited value, since the evaluating function is
        already in progress.
        """

        if is_active and not self._active_invoked:
            try:
                self._active_invoked = True
                _ = await self._lambda_coroutine()
                self._next_future.set_result(_)
            except Exception as ex:
                self._next_future.set_exception(ex)

        return await self._next_future
