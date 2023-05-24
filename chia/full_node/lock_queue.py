from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import queue
from typing import Any, AsyncIterator, Callable, Generic, Optional, Set, TypeVar

from typing_extensions import Protocol

from chia.util.log_exceptions import log_exceptions

log = logging.getLogger(__name__)


class NestedLockUnsupportedError(Exception):
    pass


class _Comparable(Protocol):
    def __lt__(self, other: Any) -> bool:
        ...


_T_Comparable = TypeVar("_T_Comparable", bound=_Comparable)


@dataclasses.dataclass(frozen=True, order=True)
class _Element(Generic[_T_Comparable]):
    priority: _T_Comparable
    # forces retention of insertion order for matching priority requests
    creation_order: float
    task: asyncio.Task[object] = dataclasses.field(compare=False)
    ready_event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event, compare=False)


@dataclasses.dataclass()
class LockQueue(Generic[_T_Comparable]):
    """
    The purpose of this class is to be able to control access to a lock, and give
    priority to certain requests.  Lower values are given access first.  To use it,
    create a lock and use the `.acquire()` context manager method:

    ```
    my_lock = LockQueue[int]()

    async with my_lock.acquire(priority=0):
       ...
    async with my_lock.acquire(priority=1):
       ...
    ```

    Must be created while an asyncio loop is running.
    """

    _queue: queue.PriorityQueue[_Element[_T_Comparable]] = dataclasses.field(default_factory=queue.PriorityQueue)
    _active: Optional[_Element[_T_Comparable]] = None
    _creation_counter: int = 0
    cancelled: Set[_Element[_T_Comparable]] = dataclasses.field(default_factory=set)

    # TODO: can we catch all unhandled errors and mark ourselves broken?
    # TODO: add debug logging

    @contextlib.asynccontextmanager
    async def acquire(
        self,
        priority: _T_Comparable,
        queued_callback: Optional[Callable[[], object]] = None,
    ) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is None:  # pragma: no cover
            # Ignoring coverage since this is an async function and thus would only be run with a current task.
            # If we can find a way to test this, we should.
            raise Exception(f"unable to check current task, got: {task}")
        if self._active is not None and self._active.task is task:
            raise NestedLockUnsupportedError()

        if self._queue.empty():
            self._creation_counter = 0
        else:
            self._creation_counter += 1
        element = _Element(priority=priority, creation_order=self._creation_counter, task=task)

        self._queue.put_nowait(element)

        if queued_callback is not None:
            with log_exceptions(log=log, consume=True):
                queued_callback()

        self._process()

        try:
            try:
                await element.ready_event.wait()
            except:  # noqa: E722
                self.cancelled.add(element)
                raise
            yield
        finally:
            if self._active is element:
                self._active = None

            self._process()

    def _process(self) -> None:
        if self._active is not None or self._queue.empty():
            return

        while True:
            element = self._queue.get_nowait()
            if element not in self.cancelled:
                break
            self.cancelled.remove(element)

        self._active = element
        element.ready_event.set()
