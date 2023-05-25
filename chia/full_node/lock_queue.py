from __future__ import annotations

import asyncio
import collections
import contextlib
import dataclasses
import logging
from enum import IntEnum
from typing import AsyncIterator, Callable, Dict, Generic, Optional, Type, TypeVar, final

from chia.util.log_exceptions import log_exceptions

log = logging.getLogger(__name__)


class NestedLockUnsupportedError(Exception):
    pass


_T_Priority = TypeVar("_T_Priority", bound=IntEnum)


@dataclasses.dataclass(frozen=True)
class _Element:
    task: asyncio.Task[object] = dataclasses.field(compare=False)
    ready_event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event, compare=False)


@final
@dataclasses.dataclass()
class LockQueue(Generic[_T_Priority]):
    """
    The purpose of this class is to be able to control access to a lock, and give
    priority to certain requests.  Lower values are given access first.  To use it,
    create a lock and use the `.acquire()` context manager method:

    ```
    my_lock = LockQueue.create(priority_type=int)

    async with my_lock.acquire(priority=0):
       ...
    async with my_lock.acquire(priority=1):
       ...
    ```
    """

    _deques: Dict[_T_Priority, collections.deque[_Element]]
    _active: Optional[_Element] = None

    # TODO: can we catch all unhandled errors and mark ourselves broken?
    # TODO: add debug logging

    @classmethod
    def create(cls, priority_type: Type[_T_Priority]) -> LockQueue[_T_Priority]:
        return cls(
            _deques={priority: collections.deque() for priority in sorted(priority_type)},
        )

    @contextlib.asynccontextmanager
    async def acquire(
        self,
        priority: _T_Priority,
        queued_callback: Optional[Callable[[], object]] = None,
    ) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is None:  # pragma: no cover
            # Ignoring coverage since this is an async function and thus would only be run with a current task.
            # If we can find a way to test this, we should.
            raise Exception(f"unable to check current task, got: {task}")
        if self._active is not None and self._active.task is task:
            raise NestedLockUnsupportedError()

        element = _Element(task=task)

        deque = self._deques[priority]
        deque.append(element)
        try:
            if queued_callback is not None:
                with log_exceptions(log=log, consume=True):
                    queued_callback()

            self._process()

            try:
                await element.ready_event.wait()
                yield
            finally:
                # another element might be active if the wait is cancelled
                if self._active is element:
                    self._active = None
        finally:
            deque.remove(element)
            self._process()

    def _process(self) -> None:
        if self._active is not None:
            return

        for deque in self._deques.values():
            if len(deque) == 0:
                continue

            element = deque[0]
            self._active = element
            element.ready_event.set()
            return
