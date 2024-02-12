from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import List

import anyio
import pytest

from chia.util.async_pool import AsyncPool, SingleUseError
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


@pytest.mark.anyio
async def test_raises_usefully_for_manage_then_run() -> None:
    async with AsyncPool.managed(
        name="test pool",
        worker_async_callable=forever_worker,
        target_worker_count=1,
    ) as pool:
        with anyio.fail_after(10):
            with pytest.raises(SingleUseError, match=AsyncPool.__name__):
                await pool.run()


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
async def test_simple_queue_example() -> None:
    inputs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    expected_outputs = [1, 4, 9, 16, 25, 36, 49, 64, 81, 100]

    input_queue = asyncio.Queue[int]()
    output_queue = asyncio.Queue[int]()

    async def worker(
        worker_id: int,
        input_queue: asyncio.Queue[int] = input_queue,
        output_queue: asyncio.Queue[int] = output_queue,
    ) -> None:
        x = await input_queue.get()
        output_queue.put_nowait(x**2)

    async with AsyncPool.managed(
        name="test pool",
        worker_async_callable=worker,
        target_worker_count=2,
    ):
        for input in inputs:
            input_queue.put_nowait(input)

        outputs: List[int] = []

        with anyio.fail_after(adjusted_timeout(10)):
            for _ in inputs:
                outputs.append(await output_queue.get())

    assert sorted(outputs) == expected_outputs
