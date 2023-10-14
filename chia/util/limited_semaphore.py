from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, Optional

from typing_extensions import final

from chia.util.log_exceptions import log_exceptions
from chia.util.misc import log_after

log_filter = "oodIXIboo"


class LimitedSemaphoreFullError(Exception):
    def __init__(self) -> None:
        super().__init__("no waiting slot available")


@final
@dataclass
class TaskInfo:
    task: asyncio.Task[object]
    acquired_time: float = field(default_factory=time.monotonic)

    def active_duration(self) -> float:
        return time.monotonic() - self.acquired_time

    def stack_string(self) -> str:
        sio = io.StringIO()
        self.task.print_stack(file=sio)
        return sio.getvalue()


@final
@dataclass
class LimitedSemaphore:
    _log: Optional[logging.Logger]
    _semaphore: asyncio.Semaphore
    _available_count: int
    _monitor_task: Optional[asyncio.Task[None]] = None
    _name: Optional[str] = None
    _active_tasks: Dict[asyncio.Task[object], TaskInfo] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        active_limit: int,
        waiting_limit: int,
        log: Optional[logging.Logger] = None,
        name: Optional[str] = None,
    ) -> LimitedSemaphore:
        self = cls(
            _semaphore=asyncio.Semaphore(active_limit),
            _available_count=active_limit + waiting_limit,
            _log=log,
            _name=name,
        )
        if self.log is not None:
            self._monitor_task = asyncio.create_task(self.monitor())
        return self

    def log(self, message: str, *args: object, **kwargs: object) -> None:
        if self._log is None:
            return

        self._log.info(f"{log_filter} {message}", *args, **kwargs)  # type: ignore[arg-type]

    async def monitor(self) -> None:
        assert self._log is not None

        with contextlib.suppress(asyncio.CancelledError):
            while True:
                with log_exceptions(
                    log=self._log,
                    message=f"{log_filter} {type(self).__name__}: unhandled exception while monitoring: ",
                    consume=True,
                ):
                    for _ in range(15):
                        await asyncio.sleep(1)
                        self.log(
                            "\n".join(
                                [
                                    f"{type(self).__name__} monitor:",
                                    f"available waiters count: {self._available_count}",
                                    f"active task count: {len(self._active_tasks)}",
                                    f"semaphore locked: {self._semaphore.locked()}",
                                    f"semaphore: {self._semaphore}",
                                ]
                            )
                        )

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[int]:
        task = asyncio.current_task()
        if task is None:
            self.log("no current task")
            assert task is not None, "this is an async def, better be in a task"

        if self._available_count < 1:
            raise LimitedSemaphoreFullError()

        self._available_count -= 1
        try:
            async with self._semaphore:
                if task in self._active_tasks:
                    self.log(f"reentering with task: {task}")
                self._active_tasks[task] = TaskInfo(task=task)
                async with contextlib.AsyncExitStack() as async_exit_stack:
                    if self._log is not None:
                        await async_exit_stack.enter_async_context(
                            log_after(
                                message=f"{type(self).__name__} ({self._name}) held by {task}",
                                delay=15,
                                log=self._log,
                            )
                        )
                    yield self._available_count
        finally:
            self._available_count += 1
            task_info = self._active_tasks.pop(task, None)
            if task_info is not None:
                self.log(f"task_info: {task_info}")

    async def close(self) -> None:
        if self._monitor_task is not None and self._log is not None:
            self._monitor_task.cancel()
            with log_exceptions(
                log=self._log,
                message=f"{log_filter} {type(self).__name__}: unhandled exception while closing: ",
                consume=True,
            ):
                await self._monitor_task
                self._monitor_task = None
