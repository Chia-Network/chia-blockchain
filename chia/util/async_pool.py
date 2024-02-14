from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import itertools
import logging
import traceback
from typing import AsyncIterator, Dict, Iterator, Protocol, final

import anyio

from chia.util.log_exceptions import log_exceptions


class InvalidTargetWorkerCountError(Exception):
    def __init__(self, o: object) -> None:
        super().__init__(f"target worker count must be one or greater: {o!r}")


class WorkerCallable(Protocol):
    async def __call__(self, worker_id: int) -> object:
        ...


@final
@dataclasses.dataclass
class AsyncPool:
    name: str
    log: logging.Logger
    worker_async_callable: WorkerCallable
    _target_worker_count: int
    _workers: Dict[asyncio.Task[object], int] = dataclasses.field(init=False, default_factory=dict)
    _worker_id_counter: Iterator[int] = dataclasses.field(init=False, default_factory=itertools.count)
    _started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    _single_use_used: bool = False

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(
        cls,
        name: str,
        worker_async_callable: WorkerCallable,
        target_worker_count: int,
        log: logging.Logger = logging.getLogger(__name__),
    ) -> AsyncIterator[AsyncPool]:
        self = cls(
            name=name,
            log=log,
            worker_async_callable=worker_async_callable,
            _target_worker_count=target_worker_count,
        )

        if self._target_worker_count < 1:
            raise InvalidTargetWorkerCountError(self._target_worker_count)

        task = asyncio.create_task(self._run(_check_single_use=False))
        try:
            # TODO: should this terminate if the run task ends?
            await self._started.wait()
            yield self
        finally:
            with anyio.CancelScope(shield=True):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _run(self, *, _check_single_use: bool = True) -> None:
        method_name = f"{type(self).__name__}._run()"

        try:
            while True:
                with log_exceptions(
                    log=self.log,
                    consume=True,
                    message=f"exception consumed while looping in {method_name} for {self.name!r}",
                ):
                    await self._run_single()
        finally:
            with anyio.CancelScope(shield=True):
                with log_exceptions(
                    log=self.log,
                    consume=False,
                    message=f"exception while tearing down in {method_name} for {self.name!r}",
                ):
                    await self._teardown_workers()

    async def _run_single(self) -> None:
        while len(self._workers) < self._target_worker_count:
            new_worker_id = next(self._worker_id_counter)
            new_worker = asyncio.create_task(self.worker_async_callable(new_worker_id))
            self.log.debug(f"{self.name}: adding worker {new_worker_id}")
            self._workers[new_worker] = new_worker_id

        self._started.set()

        self.log.debug(f"{self.name}: waiting with {len(self._workers)} workers: {list(self._workers.values())}")
        done_workers, pending_workers = await asyncio.wait(
            self._workers,
            return_when=asyncio.FIRST_COMPLETED,
        )
        done_workers_by_id = {task: self._workers[task] for task in done_workers}
        self._workers = {task: self._workers[task] for task in pending_workers}

        for task, id in done_workers_by_id.items():
            await self._handle_done_worker(task=task, id=id)

    async def _teardown_workers(self) -> None:
        while True:
            try:
                task, id = self._workers.popitem()
            except KeyError:
                break

            task.cancel()
            await self._handle_done_worker(task=task, id=id)

    async def _handle_done_worker(self, task: asyncio.Task[object], id: int) -> None:
        with anyio.CancelScope(shield=True):
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                error_trace = traceback.format_exc()
                self.log.error(f"{self.name}: worker {id} raised exception: {error_trace}")
