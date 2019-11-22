from .deferred_coroutine import deferred_coroutine


class _aiter_fork:
    """
    Implementation of an aiter fork. Traces through a linked list of aiter elements, waiting
    when necessary.
    """
    def __init__(self, next_awaitable, is_active=False):
        self._next_awaitable = next_awaitable
        self._is_active = is_active

    def __aiter__(self):
        return self

    async def __anext__(self):
        this_item, next_awaitable = await self._next_awaitable.wait(is_active=self._is_active)
        self._next_awaitable = next_awaitable
        return this_item

    def fork(self, is_active=True):
        """
        Create a new fork: either active, which uses the current task to await the next
        item; or passive, which waits until an active fork awaits it.
        """
        return _aiter_fork(self._next_awaitable, is_active=is_active)


def aiter_forker(aiter):
    """
    If you have an aiter that you would like to fork (split into multiple
    iterators, each of which produces the same elements), wrap it with this
    function.

    Returns a :class:`aiter._aiter_fork <_aiter_fork>` object that will yield
    the same objects in the same order. This object supports
    :py:func:`fork <aiter._aiter_fork.fork>`, which will let you create a
    duplicate stream.

    :type aiter: aiter
    :param aiter: an async iterator

    :return: a :class:`aiter._aiter_fork <_aiter_fork>`
    :rtype: :class:`aiter._aiter_fork <_aiter_fork>`
    """
    _open_aiter = aiter.__aiter__()

    async def get_next():
        next_item = await _open_aiter.__anext__()
        return next_item, deferred_coroutine(get_next)

    next_awaitable = deferred_coroutine(get_next)
    return _aiter_fork(next_awaitable, is_active=True)
