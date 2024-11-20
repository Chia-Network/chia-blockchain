# TODO: this should not exist, it is a bad task group that doesn't require
#       any responsibility of the requestor.

from __future__ import annotations

import asyncio
import dataclasses
import typing

T = typing.TypeVar("T")


@dataclasses.dataclass
class Pit:
    tasks: list[asyncio.Task[object]] = dataclasses.field(default_factory=list)

    def create_task(
        self,
        coroutine: typing.Coroutine[object, object, T],
        name: typing.Optional[str] = None,
    ) -> asyncio.Task[T]:
        task = asyncio.create_task(coro=coroutine, name=name)
        # TODO: consider collecting results and logging errors
        self.tasks = [task for task in self.tasks if not task.done()]
        self.tasks.append(task)
        return task


pit = Pit()
