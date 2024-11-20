# TODO: this should not exist, it is a bad task group that doesn't require
#       any responsibility of the requestor.

from __future__ import annotations

import asyncio
import dataclasses
import math
import time
import typing

T = typing.TypeVar("T")


@dataclasses.dataclass
class TaskReferencer:
    """Holds strong references to tasks until they are done.  This compensates for
    asyncio holding only weak references.  This should be replaced by patterns using
    task groups such as from anyio.
    """

    tasks: list[asyncio.Task[object]] = dataclasses.field(default_factory=list)
    clock: typing.Callable[[], float] = time.monotonic
    last_cull: float = -math.inf
    cull_period: float = 30
    cull_count: int = 1000

    def create_task(
        self,
        coroutine: typing.Coroutine[object, object, T],
        name: typing.Optional[str] = None,
    ) -> asyncio.Task[T]:
        self.maybe_cull()

        task = asyncio.create_task(coro=coroutine, name=name)
        self.tasks.append(task)

        return task

    def maybe_cull(self) -> None:
        now = self.clock()
        since_last = now - self.last_cull

        if len(self.tasks) <= self.cull_count and since_last <= self.cull_period:
            return

        # TODO: consider collecting results and logging errors
        self.tasks[:] = (task for task in self.tasks if not task.done())
        self.last_cull = now


global_task_referencer = TaskReferencer()

create_referenced_task = global_task_referencer.create_task
