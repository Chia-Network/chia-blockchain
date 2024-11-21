# TODO: this should not exist, it is a bad task group that doesn't require
#       any responsibility of the requestor.

from __future__ import annotations

import asyncio
import dataclasses
import gc
import logging
import math
import pathlib
import time
import typing

import chia
from chia.util.introspection import caller_file_and_line

T = typing.TypeVar("T")

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _TaskInfo:
    task: asyncio.Task[object]
    name: str
    known_unreferenced: bool
    creation_file: str
    creation_line: int

    def __str__(self) -> str:
        return f"{self.name} ({self.creation_file}:{self.creation_line})"


@dataclasses.dataclass
class _TaskReferencer:
    """Holds strong references to tasks until they are done.  This compensates for
    asyncio holding only weak references.  This should be replaced by patterns using
    task groups such as from anyio.
    """

    tasks: list[_TaskInfo] = dataclasses.field(default_factory=list)
    clock: typing.Callable[[], float] = time.monotonic
    last_cull: float = -math.inf
    cull_period: float = 30
    cull_count: int = 1000

    def create_task(
        self,
        coroutine: typing.Coroutine[object, object, T],
        name: typing.Optional[str] = None,
        known_unreferenced: bool = False,
    ) -> asyncio.Task[T]:
        self.report_unreferenced_tasks()
        self.maybe_cull()

        file, line = caller_file_and_line(
            distance=1,
            relative_to=(pathlib.Path(chia.__file__).parent.parent,),
        )

        task = asyncio.create_task(coro=coroutine, name=name)
        self.tasks.append(
            _TaskInfo(
                task=task,
                name=task.get_name(),
                known_unreferenced=known_unreferenced,
                creation_file=file,
                creation_line=line,
            )
        )

        return task

    def maybe_cull(self) -> None:
        now = self.clock()
        since_last = now - self.last_cull

        if len(self.tasks) <= self.cull_count and since_last <= self.cull_period:
            return

        # TODO: consider collecting results and logging errors
        self.tasks[:] = (task_info for task_info in self.tasks if not task_info.task.done())
        self.last_cull = now

    def report_unreferenced_tasks(self) -> None:
        for task_info in self.tasks:
            if task_info.known_unreferenced or task_info.task.done():
                continue

            if len(gc.get_referrers(task_info.task)) == 1:
                # presently coded to repeat every time
                logger.error(f"unexpected incomplete unreferenced task found: {task_info}")


_global_task_referencer = _TaskReferencer()

create_referenced_task = _global_task_referencer.create_task
