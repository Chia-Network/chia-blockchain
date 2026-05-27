from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import Future

import pytest

from chia.util.priority_thread_pool_executor import PriorityThreadPoolExecutor


def test_basic_submit() -> None:
    with PriorityThreadPoolExecutor(max_workers=2, thread_name_prefix="test-") as pool:
        future = pool.submit(lambda x, y: x + y, 3, 4)
        assert future.result(timeout=5) == 7


def test_submit_exception() -> None:
    with PriorityThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(int, "not_a_number")
        with pytest.raises(ValueError):
            future.result(timeout=5)


def test_nice_ordering() -> None:
    """Lower nice values should run before higher nice values."""
    barrier = threading.Event()
    results: list[int] = []
    lock = threading.Lock()

    def record(value: int) -> None:
        barrier.wait()
        with lock:
            results.append(value)

    with PriorityThreadPoolExecutor(max_workers=1, thread_name_prefix="prio-") as pool:
        blocking: Future[None] = pool.submit(barrier.wait)

        pool.submit(record, 99, nice=(10,))
        pool.submit(record, 1, nice=(1,))
        pool.submit(record, 50, nice=(5,))

        time.sleep(0.05)

        barrier.set()
        blocking.result(timeout=5)

        pool.shutdown()

    assert results == [1, 50, 99]


def test_fifo_within_same_nice() -> None:
    """Jobs with the same nice value should execute in FIFO order."""
    barrier = threading.Event()
    results: list[int] = []
    lock = threading.Lock()

    def record(value: int) -> None:
        barrier.wait()
        with lock:
            results.append(value)

    with PriorityThreadPoolExecutor(max_workers=1) as pool:
        blocking: Future[None] = pool.submit(barrier.wait)

        for i in range(5):
            pool.submit(record, i, nice=(5,))

        time.sleep(0.05)
        barrier.set()
        blocking.result(timeout=5)

        pool.shutdown()

    assert results == [0, 1, 2, 3, 4]


def test_shutdown_rejects_new_work() -> None:
    pool = PriorityThreadPoolExecutor(max_workers=1)
    pool.shutdown()
    with pytest.raises(RuntimeError, match="shut-down"):
        pool.submit(lambda: None)


def test_max_workers_respected() -> None:
    active = threading.Semaphore(0)
    max_concurrent = 0
    current = 0
    lock = threading.Lock()

    def track() -> None:
        nonlocal max_concurrent, current
        with lock:
            current += 1
            max_concurrent = max(max_concurrent, current)
        active.release()
        time.sleep(0.05)
        with lock:
            current -= 1

    max_w = 3
    with PriorityThreadPoolExecutor(max_workers=max_w, thread_name_prefix="max-") as pool:
        n_jobs = 10
        futures = [pool.submit(track) for _ in range(n_jobs)]
        for f in futures:
            f.result(timeout=10)

    assert max_concurrent <= max_w


@pytest.mark.anyio
async def test_run_in_loop() -> None:
    with PriorityThreadPoolExecutor(max_workers=2) as pool:
        result = await pool.run_in_loop(lambda x: x * 2, 21)
        assert result == 42


@pytest.mark.anyio
async def test_run_in_loop_exception() -> None:
    with PriorityThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(ValueError):
            await pool.run_in_loop(int, "bad")


@pytest.mark.anyio
async def test_run_in_loop_nice() -> None:
    """Verify nice ordering works through the async interface."""
    barrier = threading.Event()
    results: list[int] = []
    lock = threading.Lock()

    def record(value: int) -> None:
        barrier.wait()
        with lock:
            results.append(value)

    with PriorityThreadPoolExecutor(max_workers=1) as pool:
        blocking = pool.submit(barrier.wait)

        f1 = pool.run_in_loop(record, 99, nice=(10,))
        f2 = pool.run_in_loop(record, 1, nice=(1,))

        await asyncio.sleep(0.05)
        barrier.set()

        await asyncio.gather(asyncio.wrap_future(blocking), f1, f2)

    assert results == [1, 99]


def test_nice_tuple_ordering() -> None:
    """Verify that tuple nice values sort correctly, including secondary keys."""
    barrier = threading.Event()
    results: list[str] = []
    lock = threading.Lock()

    def record(value: str) -> None:
        barrier.wait()
        with lock:
            results.append(value)

    with PriorityThreadPoolExecutor(max_workers=1) as pool:
        blocking = pool.submit(barrier.wait)

        pool.submit(record, "low-fee", nice=(10, -1.0))
        pool.submit(record, "high-fee", nice=(10, -100.0))
        pool.submit(record, "block", nice=(0,))

        time.sleep(0.05)
        barrier.set()
        blocking.result(timeout=5)
        pool.shutdown()

    assert results == ["block", "high-fee", "low-fee"]


def test_context_manager() -> None:
    with PriorityThreadPoolExecutor(max_workers=1) as pool:
        f = pool.submit(lambda: 1)
        assert f.result(timeout=5) == 1
    with pytest.raises(RuntimeError):
        pool.submit(lambda: 2)


def test_invalid_max_workers() -> None:
    with pytest.raises(ValueError, match="max_workers must be positive"):
        PriorityThreadPoolExecutor(max_workers=0)


def test_invalid_dedicated() -> None:
    with pytest.raises(ValueError):
        PriorityThreadPoolExecutor(max_workers=2, dedicated=2)
    with pytest.raises(ValueError):
        PriorityThreadPoolExecutor(max_workers=2, dedicated=-1)


def test_dedicated_threads_run_dedicated_jobs() -> None:
    """Dedicated threads should pick up dedicated=True jobs even when
    general threads are fully occupied."""
    general_barrier = threading.Event()
    results: list[str] = []
    lock = threading.Lock()

    def block_general() -> str:
        general_barrier.wait()
        with lock:
            results.append("general")
        return "general"

    def dedicated_job() -> str:
        with lock:
            results.append("dedicated")
        return "dedicated"

    with PriorityThreadPoolExecutor(max_workers=2, dedicated=1, thread_name_prefix="ded-") as pool:
        general_future = pool.submit(block_general, nice=(10,))

        time.sleep(0.05)

        ded_future = pool.submit(dedicated_job, nice=(0,), dedicated=True)
        assert ded_future.result(timeout=5) == "dedicated"

        general_barrier.set()
        assert general_future.result(timeout=5) == "general"

    assert "dedicated" in results
    assert "general" in results


def test_dedicated_false_not_on_dedicated_queue() -> None:
    """Jobs with dedicated=False should never be picked up by dedicated
    threads, only by general threads."""
    barrier = threading.Event()
    thread_names: list[str | None] = []
    lock = threading.Lock()

    def record_thread() -> None:
        barrier.wait()
        with lock:
            thread_names.append(threading.current_thread().name)

    with PriorityThreadPoolExecutor(max_workers=2, dedicated=1, thread_name_prefix="t-") as pool:
        ded_blocker = pool.submit(barrier.wait, dedicated=True)

        time.sleep(0.05)

        futures = [pool.submit(record_thread, nice=(5,)) for _ in range(3)]

        time.sleep(0.05)
        barrier.set()

        ded_blocker.result(timeout=5)
        for f in futures:
            f.result(timeout=5)

    for name in thread_names:
        assert name is not None
        assert "dedicated" not in name


def test_dedicated_jobs_also_run_on_general_threads() -> None:
    """When the dedicated thread is busy, general threads should also
    be able to pick up dedicated=True jobs from the general queue."""
    barrier = threading.Event()

    with PriorityThreadPoolExecutor(max_workers=3, dedicated=1, thread_name_prefix="t-") as pool:
        ded_blocker = pool.submit(barrier.wait, dedicated=True)
        time.sleep(0.05)

        futures = [pool.submit(lambda v: v, i, dedicated=True) for i in range(4)]

        for f in futures:
            assert f.result(timeout=5) is not None

        barrier.set()
        ded_blocker.result(timeout=5)


def test_dedicated_and_general_race() -> None:
    """When a dedicated=True job is posted to both queues, only one thread
    runs it — the other hits RuntimeError on set_running_or_notify_cancel()
    and skips it.  The job must complete exactly once."""
    run_count = 0
    lock = threading.Lock()
    gate = threading.Barrier(3)

    def counted_job(v: int) -> int:
        nonlocal run_count
        with lock:
            run_count += 1
        return v

    n_jobs = 50
    with PriorityThreadPoolExecutor(max_workers=2, dedicated=1, thread_name_prefix="race-") as pool:
        # Both blockers are dedicated=True so each goes to both queues.
        # Regardless of which thread claims the first blocker, the loser
        # skips it (RuntimeError) and picks the second one from its queue.
        pool.submit(gate.wait, dedicated=True)
        pool.submit(gate.wait, dedicated=True)
        time.sleep(0.05)

        # Queue dedicated jobs while both threads are blocked
        futures = [pool.submit(counted_job, i, dedicated=True) for i in range(n_jobs)]

        # Release both threads — they race over the same items
        gate.wait(timeout=5)

        results = sorted(f.result(timeout=10) for f in futures)

    assert results == list(range(n_jobs))
    assert run_count == n_jobs


def test_no_dedicated_threads() -> None:
    """With dedicated=0 (default), dedicated=True on submit is a no-op."""
    with PriorityThreadPoolExecutor(max_workers=2) as pool:
        f = pool.submit(lambda: 42, dedicated=True)
        assert f.result(timeout=5) == 42
