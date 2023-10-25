from __future__ import annotations

import asyncio
import collections
import contextlib
import dataclasses
import logging
import traceback
from enum import IntEnum
from typing import AsyncIterator, Dict, Generic, Optional, Type, TypeVar

from typing_extensions import final

from chia.util.log_exceptions import log_exceptions
from chia.util.misc import log_after, log_filter


class NestedLockUnsupportedError(Exception):
    pass


_T_Priority = TypeVar("_T_Priority", bound=IntEnum)


@dataclasses.dataclass(frozen=True)
class _Element:
    task: asyncio.Task[object] = dataclasses.field(compare=False)
    ready_event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event, compare=False)


@final
@dataclasses.dataclass()
class PriorityMutex(Generic[_T_Priority]):
    """
    The purpose of this class is to be able to control access to a mutex, and give
    priority to certain requests.  Lower values are given access first.  To use it,
    create a mutex and use the `.acquire()` context manager method.  In actual uses,
    a dedicated priority enumeration is likely to be more clear.

    ```
    my_mutex = PriorityMutex.create(priority_type=int)

    async with my_mutex.acquire(priority=0):
       ...
    async with my_mutex.acquire(priority=1):
       ...
    ```
    """

    _deques: Dict[_T_Priority, collections.deque[_Element]]
    _log: logging.Logger
    _active: Optional[_Element] = None
    _monitor_task: Optional[asyncio.Task[None]] = None

    @classmethod
    def create(cls, priority_type: Type[_T_Priority], log: logging.Logger) -> PriorityMutex[_T_Priority]:
        self = cls(
            _deques={priority: collections.deque() for priority in sorted(priority_type)},
            _log=log,
        )
        self._monitor_task = asyncio.create_task(self.monitor())

        return self

    async def monitor(self) -> None:
        assert self._log is not None

        with contextlib.suppress(asyncio.CancelledError):
            while True:
                with log_exceptions(
                    log=self._log,
                    message=f"{log_filter} {type(self).__name__}: unhandled exception while monitoring: ",
                    consume=True,
                ):
                    await asyncio.sleep(2)

                    self._log.info(
                        "\n".join(
                            [
                                f"{log_filter} {type(self).__name__} monitor:",
                                f"active: {self._active}",
                                *(f"{priority}: {len(deque)}" for priority, deque in self._deques.items()),
                            ]
                        )
                    )

    @contextlib.asynccontextmanager
    async def acquire(
        self,
        priority: _T_Priority,
    ) -> AsyncIterator[None]:
        stack = "\n".join(traceback.format_stack())
        task = asyncio.current_task()
        self._log.info(f"{log_filter} {type(self).__name__}.acquire() entered: {task}\n\n{stack}")
        with log_exceptions(
            log=self._log,
            message=f"{log_filter} {type(self).__name__}.acquire() ({task}) logging exception",
        ):
            if task is None:
                raise Exception(f"unable to check current task, got: {task!r}")
            self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) task is not None")
            if self._active is not None and self._active.task is task:
                self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) nested, raising")
                raise NestedLockUnsupportedError()

            self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) creating element")
            element = _Element(task=task)
            self._log.info(
                f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) element created: {element}"
            )

            deque = self._deques[priority]
            self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) selected deque")
            deque.append(element)
            self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) appended element")
            try:
                if self._active is None:
                    self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) nothing active")
                    self._active = element
                    self._log.info(
                        f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) set self to active"
                    )
                else:
                    self._log.info(
                        f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()})"
                        + f" waiting on existing active element: {self._active}"
                    )
                    await element.ready_event.wait()
                self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) entering log_after()")
                # TODO: lazy and not configurable since we presently have just one use, kinda
                async with log_after(
                    message=f"{log_filter} {type(self).__name__} held by {task}",
                    delay=15,
                    log=self._log,
                ):
                    self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) yielding")
                    yield
                    self._log.info(
                        f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) after yield, no exception"
                    )
            finally:
                self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) finally")
                # another element might be active if the wait is cancelled
                if self._active is element:
                    self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) deactivating")
                    self._active = None
                    self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) deactivated")
                self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) about to remove")
                deque.remove(element)
                self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) removed")

                if self._active is None:
                    self._log.info(
                        f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()})"
                        + " nothing active, looking for something"
                    )
                    for deque in self._deques.values():
                        self._log.info(
                            f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()})"
                            + f" checking deque length: {len(deque)}"
                        )
                        if len(deque) == 0:
                            self._log.info(
                                f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()})"
                                + " skipping empty deque",
                            )
                            continue

                        self._log.info(
                            f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) getting element 0"
                        )
                        element = deque[0]
                        self._log.info(
                            f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) got: {element}"
                        )
                        self._active = element
                        self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) set active")
                        element.ready_event.set()
                        self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) set event")
                        break
                    self._log.info(
                        f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) end of if active is none"
                    )
                self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) end of finally")
            self._log.info(f"{log_filter} {type(self).__name__}.acquire() ({task.get_name()}) end of method")
