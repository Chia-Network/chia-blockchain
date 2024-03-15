from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import itertools
import logging
import traceback
from typing import AsyncIterator, Dict, Generic, Iterator, Optional, Protocol, TypeVar, final

import anyio

from chia.util.log_exceptions import log_exceptions


class InvalidTargetWorkerCountError(Exception):
    def __init__(self, o: object) -> None:
        super().__init__(f"target worker count must be one or greater: {o!r}")


class WorkerCallable(Protocol):
    async def __call__(self, worker_id: int) -> object: ...


J = TypeVar("J")
R = TypeVar("R")
T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)
T_contra = TypeVar("T_contra", contravariant=True)


class QueuedWorkerCallable(Protocol[T, T_co]):
    async def __call__(self, worker_id: int, job: Job[T]) -> T_co: ...


class JobQueueProtocol(Protocol[T_co]):
    async def get(self) -> T_co: ...


class ResultQueueProtocol(Protocol[T_contra]):
    async def put(self, item: T_contra) -> None: ...


# TODO: how does this compare to just using a future
@dataclasses.dataclass
class Job(Generic[T]):
    input: T
    started: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    done: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    exception: Optional[BaseException] = None
    task: Optional[asyncio.Task[object]] = None
    cancelled: bool = False


@final
@dataclasses.dataclass
class QueuedAsyncPool(Generic[J, R]):
    name: str
    job_queue: JobQueueProtocol[Job[J]]
    result_queue: Optional[ResultQueueProtocol[R]]
    worker_async_callable: QueuedWorkerCallable[J, R]

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(
        cls,
        name: str,
        job_queue: JobQueueProtocol[Job[J]],
        worker_async_callable: QueuedWorkerCallable[J, R],
        target_worker_count: int,
        result_queue: Optional[ResultQueueProtocol[R]] = None,
        log: logging.Logger = logging.getLogger(__name__),
    ) -> AsyncIterator[QueuedAsyncPool[J, R]]:
        self = cls(
            name=name,
            job_queue=job_queue,
            result_queue=result_queue,
            worker_async_callable=worker_async_callable,
        )

        async with AsyncPool.managed(
            name=self.name,
            worker_async_callable=self.worker,
            target_worker_count=target_worker_count,
            log=log,
        ):
            yield self

    async def get_job(self) -> Job[J]:
        while True:
            job = await self.job_queue.get()
            if not job.cancelled:
                # TODO: can the job just be removed from the queue?
                return job

    async def worker(self, worker_id: int) -> None:
        job = await self.get_job()
        job.task = asyncio.current_task()
        job.started.set()

        try:
            result = await self.worker_async_callable(worker_id=worker_id, job=job)
        except BaseException as e:
            # TODO: can't you not raise the same exception twice so this has to be
            #       just reference and is all...  well, i dunno.
            job.exception = e
            raise
        else:
            if self.result_queue is not None:
                await self.result_queue.put(result)
        finally:
            job.done.set()

    def cancel(self, job: Job[J]) -> None:
        # TODO: should this just be on the Job object?  or can we do something useful
        #       here like get it out of the queue.
        job.cancelled = True
        if job.task is not None:
            job.task.cancel()
        # TODO: should this happen only after actual cancellation completes?
        job.done.set()


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
