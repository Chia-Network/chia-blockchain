from __future__ import annotations

import asyncio
import logging
import time
import random
from typing import Awaitable, TypeVar


T = TypeVar("T")


class TaskWrapper:
    def __init__(self) -> None:
        self.log = logging.getLogger(__name__)
        self.log.setLevel(logging.INFO)
        self.log.addHandler(logging.FileHandler('tasks.txt'))
        self.task_list = []
        self.task_lock = asyncio.Lock()


    async def reap_tasks(self, these_tasks: List[asyncio.Task[T]]) -> None:
        async with self.task_lock:
            for task in these_tasks:
                self.task_list = list(filter(lambda t: id(t) == id(this_task), self.task_list))


    async def log_task(self, log: logging.Logger, title: str, task: asyncio.Task[T]) -> asyncio.Task[T]:
        """Given a task, make an enwrapping task that announces when it starts and
           ends via a logger."""

        # A holder for tasks created here.  The inner task is awaited.
        # This is carried off by reference for use in the finally below.
        task_holder = []

        async def enwrapped():
            start_time = time.time()
            self.log.debug(f"{id(task)}: starting task {title}")
            try:
                return await task
            except BaseException as e:
                self.log.error(
                    f"{id(task)} task {title} ended via exception {traceback.format_exception(e)} after {time.time() - start_time}s"
                )
            finally:
                await self.reap_tasks(task_holder)
                self.log.debug(f"{id(task)}: task finished {title} in {time.time() - start_time}s")

        task = asyncio.create_task(enwrapped())
        task_holder.append(task)

        # Ensure this task is tracked.
        async with self.task_lock:
            self.task_list.append(task)

        return task


_task_wrapper = TaskWrapper()


def create_task(log: logging.Logger, title: str, cb: Awaitable[T]) -> asyncio.Task[T]:
    return _task_wrapper.log_task(log, title, asyncio.create_task(cb))
