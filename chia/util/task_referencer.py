# TODO: this should not exist, it is a bad task group that doesn't require
#       any responsibility of the requestor.

from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
import time
import typing

T = typing.TypeVar("T")

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _TaskInfo:
    task: asyncio.Task[object]
    name: str
    known_unreferenced: bool

    def __str__(self) -> str:
        return self.name


@dataclasses.dataclass
class _TaskReferencer:
    """Holds strong references to tasks until they are done.  This compensates for
    asyncio holding only weak references.  This should be replaced by patterns using
    task groups such as from anyio.
    """

    tasks: list[_TaskInfo] = dataclasses.field(default_factory=list)
    clock: typing.Callable[[], float] = time.monotonic
    last_cull_time: float = -math.inf
    last_cull_length: int = 0
    cull_period: float = 30
    cull_count: int = 1000

    def create_task(
        self,
        coroutine: typing.Coroutine[object, object, T],
        *,
        name: typing.Optional[str] = None,
        known_unreferenced: bool = False,
    ) -> asyncio.Task[T]:
        self.maybe_cull()

        task = asyncio.create_task(coro=coroutine, name=name)  # noqa: TID251
        self.tasks.append(
            _TaskInfo(
                task=task,
                name=task.get_name(),
                known_unreferenced=known_unreferenced,
            )
        )

        return task

    def maybe_cull(self) -> None:
        now = self.clock()
        since_last = now - self.last_cull_time

        if len(self.tasks) <= self.last_cull_length + self.cull_count and since_last <= self.cull_period:
            return

        # TODO: consider collecting results and logging errors
        self.tasks = [task_info for task_info in self.tasks if not task_info.task.done()]
        self.last_cull_time = now
        self.last_cull_length = len(self.tasks)


_global_task_referencer = _TaskReferencer()

create_referenced_task = _global_task_referencer.create_task
