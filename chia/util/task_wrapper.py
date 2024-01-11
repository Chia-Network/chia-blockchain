from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, TypeVar

T = TypeVar("T")


def log_task(log: logging.Logger, title: str, task: asyncio.Task[T]) -> asyncio.Task[T]:
    """Given a task, make an enwrapping task that announces when it starts and
    ends via a logger."""

    async def enwrapped():
        start_time = time.time()
        log.debug(f"{id(task)}: starting task {title}")
        try:
            return await task
        except BaseException as e:
            log.error(
                f"{id(task)} task {title} ended via exception {traceback.format_exception(e)} after {time.time() - start_time}s"
            )
        finally:
            log.debug(f"{id(task)}: task finished {title} in {time.time() - start_time}s")

    return asyncio.create_task(enwrapped())


def create_task(log: logging.Logger, title: str, cb: Awaitable[T]) -> asyncio.Task[T]:
    return log_task(log, title, asyncio.create_task(cb))
