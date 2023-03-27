from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from typing import Any, AsyncIterator, Generic, Optional, Set, TypeVar

from typing_extensions import Protocol

log = logging.getLogger(__name__)


class _Comparable(Protocol):
    def __lt__(self, other: Any) -> bool:
        ...


_T_Comparable = TypeVar("_T_Comparable", bound=_Comparable)


@dataclasses.dataclass(frozen=True, order=True)
class _Element(Generic[_T_Comparable]):
    priority: _T_Comparable
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

    _queue: asyncio.PriorityQueue[_Element[_T_Comparable]] = dataclasses.field(default_factory=asyncio.PriorityQueue)
    _active: Optional[_Element[_T_Comparable]] = None
    cancelled: Set[_Element[_T_Comparable]] = dataclasses.field(default_factory=set)

    @contextlib.asynccontextmanager
    async def acquire(self, priority: _T_Comparable) -> AsyncIterator[None]:
        element = _Element(priority=priority)

        await self._queue.put(element)
        await self._process()

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
            await self._process()

    async def _process(self) -> None:
        if self._active is not None or self._queue.empty():
            return

        while True:
            element = await self._queue.get()
            if element not in self.cancelled:
                break
            self.cancelled.remove(element)

        self._active = element
        element.ready_event.set()
