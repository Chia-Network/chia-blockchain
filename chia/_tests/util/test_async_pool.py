from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple, Type

import anyio
import pytest

from chia.util.async_pool import AsyncPool, InvalidTargetWorkerCountError, Job, QueuedAsyncPool
from chia.util.timing import adjusted_timeout


async def forever_worker(worker_id: int) -> None:
    forever = asyncio.Event()
    await forever.wait()


@pytest.mark.parametrize("count", [1, 2, 10, 1000])
@pytest.mark.anyio
async def test_creates_expected_worker_count_immediately(count: int) -> None:
    async with AsyncPool.managed(
        name="test pool",
        worker_async_callable=forever_worker,
        target_worker_count=count,
    ) as pool:
        assert len(pool._workers) == count


@pytest.mark.parametrize("count", [1, 2, 10, 1000])
@pytest.mark.anyio
async def test_workers_list_empty_after_management(count: int) -> None:
    async with AsyncPool.managed(
        name="test pool",
        worker_async_callable=forever_worker,
        target_worker_count=count,
    ) as pool:
        assert len(pool._workers) == count

    assert len(pool._workers) == 0


@pytest.mark.parametrize(argnames="count", argvalues=[-5, 0])
@pytest.mark.anyio
async def test_managed_raises_usefully_for_invalid_target_count(count: int) -> None:
    with pytest.raises(InvalidTargetWorkerCountError, match=f"{count}"):
        async with AsyncPool.managed(
            name="test pool",
            worker_async_callable=forever_worker,
            target_worker_count=count,
        ):
            # testing that the context manager raises on entry so we should never
            # cover below
            pass  # pragma: no cover


@pytest.mark.parametrize("count", [1, 2, 10, 1000])
@pytest.mark.anyio
async def test_does_not_exceed_expected_concurrency(count: int) -> None:
    short_time = 0.000_1
    long_time = 50 * short_time

    @dataclass
    class InstrumentedWorkers:
        current: int = 0
        peak: int = 0

        async def work(self, worker_id: int) -> None:
            self.current += 1
            self.peak = max(self.peak, self.current)
            plus_minus = 0.1
            percentage = (random.random() * 2 * plus_minus) - plus_minus
            try:
                await asyncio.sleep(short_time * (1 + percentage))
            finally:
                self.current -= 1

    instrumented_workers = InstrumentedWorkers()

    async with AsyncPool.managed(
        name="test pool",
        worker_async_callable=instrumented_workers.work,
        target_worker_count=count,
    ):
        await asyncio.sleep(long_time)

    assert instrumented_workers.peak == count


@pytest.mark.anyio
async def test_worker_id_counts() -> None:
    expected_results = [0, 1, 2, 3, 4, 5]

    result_queue: asyncio.Queue[int] = asyncio.Queue()

    async def worker(
        worker_id: int,
        result_queue: asyncio.Queue[int] = result_queue,
        hang_on_worker_id: int = expected_results[-1],
    ) -> None:
        await result_queue.put(worker_id)
        if worker_id == hang_on_worker_id:
            forever = asyncio.Event()
            await forever.wait()

    async with AsyncPool.managed(
        name="test pool",
        worker_async_callable=worker,
        target_worker_count=1,
    ):
        results: List[int] = []

        with anyio.fail_after(adjusted_timeout(10)):
            for _ in expected_results:
                results.append(await result_queue.get())

    assert results == expected_results


@pytest.mark.anyio
async def test_worker_exception_logged(caplog: pytest.LogCaptureFixture) -> None:
    expected_name = "test pool"
    expected_message = "this is the exception message"

    class CustomException(Exception):
        def __init__(self) -> None:
            super().__init__(expected_message)

    work_queue: asyncio.Queue[Optional[Exception]] = asyncio.Queue()
    result_queue: asyncio.Queue[None] = asyncio.Queue()

    async def worker(
        worker_id: int,
        work_queue: asyncio.Queue[Optional[Exception]] = work_queue,
        result_queue: asyncio.Queue[None] = result_queue,
    ) -> None:
        work = await work_queue.get()

        if work is None:
            await result_queue.put(None)
        else:
            raise work

    async with AsyncPool.managed(
        name=expected_name,
        worker_async_callable=worker,
        target_worker_count=1,
    ):
        await work_queue.put(CustomException())
        await work_queue.put(None)

        with anyio.fail_after(adjusted_timeout(10)):
            # wait until the second worker has processed the input to be sure the
            # first worker has raised and the result has been processed
            await result_queue.get()

        # located inside the pool manager as leaving should not be required for
        # logging to happen
        log_text = caplog.text
        match = re.search(
            pattern=(
                f"{re.escape(expected_name)}: .*"
                + f"{re.escape(CustomException.__name__)}: {re.escape(expected_message)}"
            ),
            string=log_text,
            flags=re.DOTALL,
        )
        assert match is not None, repr(log_text)


@pytest.mark.anyio
async def test_simple_queue_example() -> None:
    inputs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    expected_results = [1, 4, 9, 16, 25, 36, 49, 64, 81, 100]

    work_queue: asyncio.Queue[int] = asyncio.Queue()
    result_queue: asyncio.Queue[int] = asyncio.Queue()

    async def worker(
        worker_id: int,
        work_queue: asyncio.Queue[int] = work_queue,
        result_queue: asyncio.Queue[int] = result_queue,
    ) -> None:
        x = await work_queue.get()
        await result_queue.put(x**2)

    async with AsyncPool.managed(
        name="test pool",
        worker_async_callable=worker,
        target_worker_count=2,
    ):
        for input in inputs:
            await work_queue.put(input)

        results: List[int] = []

        with anyio.fail_after(adjusted_timeout(10)):
            for _ in inputs:
                results.append(await result_queue.get())

    assert sorted(results) == expected_results


@pytest.mark.anyio
async def test_simple_queue_example_using_queued() -> None:
    inputs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    expected_results = [1, 4, 9, 16, 25, 36, 49, 64, 81, 100]

    work_queue: asyncio.Queue[Job[int]] = asyncio.Queue()
    result_queue: asyncio.Queue[int] = asyncio.Queue()

    async def worker(
        worker_id: int,
        job: Job[int],
    ) -> int:
        return job.input**2

    async with QueuedAsyncPool.managed(
        name="test pool",
        job_queue=work_queue,
        result_queue=result_queue,
        worker_async_callable=worker,
        target_worker_count=2,
    ):
        jobs = [Job(input=input) for input in inputs]
        for job in jobs:
            await work_queue.put(job)

        results: List[int] = []

        with anyio.fail_after(adjusted_timeout(10)):
            for _ in expected_results:
                results.append(await result_queue.get())

    assert sorted(results) == expected_results


@pytest.mark.anyio
async def test_queued_pre_cancel() -> None:
    cancel = {4, 7}
    inputs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    expected_results = [1, 4, 9, 25, 36, 64, 81, 100]

    work_queue: asyncio.Queue[Job[int]] = asyncio.Queue()
    result_queue: asyncio.Queue[int] = asyncio.Queue()

    async def worker(
        worker_id: int,
        job: Job[int],
    ) -> int:
        return job.input**2

    async with QueuedAsyncPool.managed(
        name="test pool",
        job_queue=work_queue,
        result_queue=result_queue,
        worker_async_callable=worker,
        target_worker_count=2,
    ) as pool:
        jobs = [Job(input=input) for input in inputs]
        for job in jobs:
            if job.input in cancel:
                pool.cancel(job=job)

            await work_queue.put(job)

        results: List[int] = []

        with anyio.fail_after(adjusted_timeout(10)):
            for _ in expected_results:
                results.append(await result_queue.get())

    assert sorted(results) == expected_results


@pytest.mark.anyio
async def test_queued_active_cancel() -> None:
    cancel = {4, 7}
    inputs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    expected_results = [1, 4, 9, 25, 36, 64, 81, 100]

    work_queue: asyncio.Queue[Job[int]] = asyncio.Queue()
    result_queue: asyncio.Queue[int] = asyncio.Queue()

    async def worker(
        worker_id: int,
        job: Job[int],
    ) -> int:
        if job.input in cancel:
            forever = asyncio.Event()
            await forever.wait()
        return job.input**2

    async with QueuedAsyncPool.managed(
        name="test pool",
        job_queue=work_queue,
        result_queue=result_queue,
        worker_async_callable=worker,
        target_worker_count=2,
    ) as pool:
        jobs = [Job(input=input) for input in inputs]
        for job in jobs:
            await work_queue.put(job)

        results: List[int] = []
        with anyio.fail_after(adjusted_timeout(10)):
            for job in jobs:
                await job.started.wait()

                if job.input in cancel:
                    pool.cancel(job=job)
                else:
                    results.append(await result_queue.get())

    assert sorted(results) == expected_results


@pytest.mark.anyio
async def test_queued_raises() -> None:
    raises = {4, 7}
    inputs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    expected_results = [1, 4, 9, 25, 36, 64, 81, 100]

    work_queue: asyncio.Queue[Job[int]] = asyncio.Queue()
    result_queue: asyncio.Queue[int] = asyncio.Queue()

    async def worker(
        worker_id: int,
        job: Job[int],
    ) -> int:
        if job.input in raises:
            raise Exception(job.input)

        return job.input**2

    async with QueuedAsyncPool.managed(
        name="test pool",
        job_queue=work_queue,
        result_queue=result_queue,
        worker_async_callable=worker,
        target_worker_count=2,
    ):
        jobs = [Job(input=input) for input in inputs]
        for job in jobs:
            await work_queue.put(job)

        results: List[int] = []

        with anyio.fail_after(adjusted_timeout(10)):
            for _ in expected_results:
                results.append(await result_queue.get())

    raising_jobs = [job for job in jobs if job.input in raises]
    expected_exceptions = [(Exception, (job.input,)) for job in raising_jobs]

    exceptions: List[Tuple[Type[BaseException], Tuple[int]]] = []
    for job in raising_jobs:
        exception = job.exception
        assert isinstance(exception, BaseException)
        exceptions.append((type(exception), exception.args))

    assert exceptions == expected_exceptions

    assert sorted(results) == expected_results
