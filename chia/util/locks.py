"""Synchronization primitives."""

import collections

from asyncio import exceptions
from asyncio import mixins
from asyncio import tasks


class _ContextManagerMixin:
    async def __aenter__(self):
        await self.acquire()
        # We have no use for the "as ..."  clause in the with
        # statement for locks.
        return None

    async def __aexit__(self, exc_type, exc, tb):
        self.release()

class Semaphore(_ContextManagerMixin, mixins._LoopBoundMixin):
    """A Semaphore implementation.

    A semaphore manages an internal counter which is decremented by each
    acquire() call and incremented by each release() call. The counter
    can never go below zero; when acquire() finds that it is zero, it blocks,
    waiting until some other thread calls release().

    Semaphores also support the context management protocol.

    The optional argument gives the initial value for the internal
    counter; it defaults to 1. If the value given is less than 0,
    ValueError is raised.
    """

    def __init__(self, value=1, *, loop=mixins._marker):
        super().__init__(loop=loop)
        if value < 0:
            raise ValueError("Semaphore initial value must be >= 0")
        self._value = value
        self._waiters = collections.deque()
        self._wakeup_scheduled = False

    def __repr__(self):
        res = super().__repr__()
        extra = 'locked' if self.locked() else f'unlocked, value:{self._value}'
        if self._waiters:
            extra = f'{extra}, waiters:{len(self._waiters)}'
        return f'<{res[1:-1]} [{extra}]>'

    def _wake_up_next(self):
        while self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                self._wakeup_scheduled = True
                return

    def locked(self):
        """Returns True if semaphore can not be acquired immediately."""
        return self._value == 0

    async def acquire(self):
        """Acquire a semaphore.

        If the internal counter is larger than zero on entry,
        decrement it by one and return True immediately.  If it is
        zero on entry, block, waiting until some other coroutine has
        called release() to make it larger than 0, and then return
        True.
        """
        # _wakeup_scheduled is set if *another* task is scheduled to wakeup
        # but its acquire() is not resumed yet
        while self._wakeup_scheduled or self._value <= 0:
            fut = self._get_loop().create_future()
            self._waiters.append(fut)
            try:
                await fut
                # reset _wakeup_scheduled *after* waiting for a future
                self._wakeup_scheduled = False
            except exceptions.CancelledError:
                if len(self._waiters) == 0:
                    self._wakeup_scheduled = False
                self._wake_up_next()
                raise
        self._value -= 1
        return True

    def release(self):
        """Release a semaphore, incrementing the internal counter by one.
        When it was zero on entry and another coroutine is waiting for it to
        become larger than zero again, wake up that coroutine.
        """
        self._value += 1
        self._wake_up_next()
