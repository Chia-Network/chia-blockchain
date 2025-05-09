# TODO: this should not exist, it is a bad task group that doesn't require
#       any responsibility of the requestor.

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import typing

import anyio

T = typing.TypeVar("T")

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _TaskInfo:
    task: asyncio.Task[object]
    # retained for potential debugging use
    known_unreferenced: bool

    def __str__(self) -> str:
        return self.task.get_name()


@dataclasses.dataclass
class _TaskReferencer:
    """Holds strong references to tasks until they are done.  This compensates for
    asyncio holding only weak references.  This should be replaced by patterns using
    task groups such as from anyio.
    """

    tasks: dict[asyncio.Task[object], _TaskInfo] = dataclasses.field(default_factory=dict)

    @contextlib.asynccontextmanager
    async def manage_task_cancel_on_exit(
        self,
        coroutine: typing.Coroutine[object, object, T],
        *,
        name: typing.Optional[str] = None,
    ) -> typing.AsyncIterator[asyncio.Task[T]]:
        task = create_referenced_task(coroutine, name=name, known_unreferenced=False)
        done = asyncio.Event()
        task.add_done_callback(lambda _: done.set())
        try:
            yield task
        finally:
            with anyio.CancelScope(shield=True):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    def create_task(
        self,
        coroutine: typing.Coroutine[object, object, T],
        *,
        name: typing.Optional[str] = None,
        known_unreferenced: bool = False,
    ) -> asyncio.Task[T]:
        task = asyncio.create_task(coro=coroutine, name=name)  # noqa: TID251
        task.add_done_callback(self._task_done)

        self.tasks[task] = _TaskInfo(task=task, known_unreferenced=known_unreferenced)

        return task

    def _task_done(self, task: asyncio.Task[object]) -> None:
        # TODO: consider collecting results and logging errors
        try:
            del self.tasks[task]
        except KeyError:
            logger.warning("Task not found in task referencer: %s", task)


_global_task_referencer = _TaskReferencer()

create_referenced_task = _global_task_referencer.create_task
manage_referenced_task_cancel_on_exit = _global_task_referencer.manage_task_cancel_on_exit
