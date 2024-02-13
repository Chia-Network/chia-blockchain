from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import itertools
import logging
import traceback
from typing import AsyncIterator, Dict, Iterator, Protocol, final

import anyio


class SingleUseError(Exception):
    def __init__(self, o: object) -> None:
        super().__init__(f"single use object has already been used: {o!r}")


class WorkerCallable(Protocol):
    async def __call__(self, worker_id: int) -> object:
        ...


# TODO: require that target count be greater than zero


@final
@dataclasses.dataclass
class AsyncPool:
    name: str
    log: logging.Logger
    worker_async_callable: WorkerCallable
    target_worker_count: int
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
            target_worker_count=target_worker_count,
        )

        self.check_single_use()

        task = asyncio.create_task(self.run(_check_single_use=False))
        await self._started.wait()

        # TODO: should this terminate if the run task ends?

        try:
            yield self
        finally:
            with anyio.CancelScope(shield=True):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    def check_single_use(self) -> None:
        if self._single_use_used:
            raise SingleUseError(self)
        self._single_use_used = True

    async def run(self, *, _check_single_use: bool = True) -> None:
        # TODO: should this just be private?
        if _check_single_use:
            self.check_single_use()

        try:
            while True:
                while len(self._workers) < self.target_worker_count:
                    new_worker_id = next(self._worker_id_counter)
                    new_worker = asyncio.create_task(self.worker_async_callable(new_worker_id))
                    self.log.debug(f"{self.name}: adding worker {new_worker_id}")
                    self._workers[new_worker] = new_worker_id

                self._started.set()

                self.log.debug(
                    f"{self.name}: waiting with {len(self._workers)} workers: {list(self._workers.values())}"
                )
                done_workers, pending_workers = await asyncio.wait(
                    self._workers,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                done_workers_by_id = {task: self._workers[task] for task in done_workers}
                self._workers = {task: self._workers[task] for task in pending_workers}

                for task, id in done_workers_by_id.items():
                    await self.handle_done_worker(
                        task=task,
                        id=id,
                        consume_cancellation=False,
                    )
        finally:
            with anyio.CancelScope(shield=True):
                # TODO: would be nice to not need a list to avoid modifying while iterating
                for task, id in list(self._workers.items()):
                    task.cancel()
                    await self.handle_done_worker(
                        task=task,
                        id=id,
                        consume_cancellation=True,
                    )

    async def handle_done_worker(self, task: asyncio.Task[object], id: int, consume_cancellation: bool) -> None:
        with anyio.CancelScope(shield=True):
            try:
                await task
            except asyncio.CancelledError:
                if not consume_cancellation:
                    raise
            except Exception:
                error_trace = traceback.format_exc()
                self.log.debug(f"{self.name}: worker {id} raised exception: {error_trace}")
