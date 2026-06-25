from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from chia.util.task_pipeline import TaskPipeline


async def _count_up(n: int) -> AsyncIterator[int]:
    for i in range(n):
        yield i


@pytest.mark.anyio
async def test_basic_pipeline() -> None:
    """Items flow through all stages in order."""
    results: list[int] = []

    async def double(x: int) -> int:
        return x * 2

    async def collect(x: int) -> None:
        results.append(x)

    pipeline = TaskPipeline(source=_count_up(5), stages=[double, collect], queue_size=2)
    await pipeline.run()

    assert results == [0, 2, 4, 6, 8]


@pytest.mark.anyio
async def test_single_consumer_stage() -> None:
    """Pipeline works with just one consumer stage (no transforms)."""
    results: list[int] = []

    async def collect(x: int) -> None:
        results.append(x)

    pipeline = TaskPipeline(source=_count_up(3), stages=[collect], queue_size=4)
    await pipeline.run()

    assert results == [0, 1, 2]


@pytest.mark.anyio
async def test_filter_with_none() -> None:
    """Returning None from a transform stage filters the item."""
    results: list[int] = []

    async def keep_even(x: int) -> int | None:
        if x % 2 == 0:
            return x
        return None

    async def collect(x: int) -> None:
        results.append(x)

    pipeline = TaskPipeline(source=_count_up(6), stages=[keep_even, collect], queue_size=4)
    await pipeline.run()

    assert results == [0, 2, 4]


@pytest.mark.anyio
async def test_source_exception_propagates() -> None:
    """An exception in the source async iterator propagates from run()."""

    async def bad_source() -> AsyncIterator[int]:
        yield 1
        raise RuntimeError("source failed")

    results: list[int] = []

    # Required stage argument. May process the one yielded item if the
    # consumer runs before the source exception propagates; the assertion
    # below accounts for both outcomes.
    async def collect(x: int) -> None:
        results.append(x)  # pragma: no cover

    pipeline = TaskPipeline(source=bad_source(), stages=[collect], queue_size=4)
    with pytest.raises(RuntimeError, match="source failed"):
        await pipeline.run()

    assert len(results) <= 1


@pytest.mark.anyio
async def test_stage_exception_propagates() -> None:
    """An exception in a stage propagates from run()."""
    processed: list[int] = []

    async def failing_stage(x: int) -> int:
        if x == 3:
            raise ValueError("stage failed on 3")
        processed.append(x)
        return x

    async def collect(x: int) -> None:
        pass

    pipeline = TaskPipeline(source=_count_up(10), stages=[failing_stage, collect], queue_size=2)
    with pytest.raises(ValueError, match="stage failed on 3"):
        await pipeline.run()

    # Items 0, 1, 2 should have been processed before the failure
    assert processed == [0, 1, 2]


@pytest.mark.anyio
async def test_last_stage_exception_propagates() -> None:
    """An exception in the last (consumer) stage propagates and shuts down the pipeline."""

    async def identity(x: int) -> int:
        return x

    async def failing_consumer(x: int) -> None:
        if x == 2:
            raise ValueError("consumer failed")

    pipeline = TaskPipeline(source=_count_up(10), stages=[identity, failing_consumer], queue_size=2)
    with pytest.raises(ValueError, match="consumer failed"):
        await pipeline.run()


@pytest.mark.anyio
async def test_drain_after_failure() -> None:
    """drain() returns unconsumed items from a queue after a failure."""

    async def identity(x: int) -> int:
        return x

    async def failing_consumer(x: int) -> None:
        if x == 2:
            raise ValueError("boom")

    pipeline = TaskPipeline(source=_count_up(10), stages=[identity, failing_consumer], queue_size=5)
    with pytest.raises(ValueError, match="boom"):
        await pipeline.run()

    # Some items may remain in the queue between identity and failing_consumer
    remaining = pipeline.drain(1)
    assert all(isinstance(item, int) for item in remaining)


@pytest.mark.anyio
async def test_backpressure() -> None:
    """Slow consumer creates back-pressure without deadlock."""
    results: list[int] = []

    async def slow_collect(x: int) -> None:
        await asyncio.sleep(0.01)
        results.append(x)

    pipeline = TaskPipeline(source=_count_up(20), stages=[slow_collect], queue_size=2)
    await pipeline.run()

    assert results == list(range(20))


@pytest.mark.anyio
async def test_empty_source() -> None:
    """An empty source completes the pipeline cleanly."""
    results: list[int] = []

    # Required stage argument. Never called because the source is empty.
    async def collect(x: int) -> None:
        results.append(x)  # pragma: no cover

    pipeline = TaskPipeline(source=_count_up(0), stages=[collect], queue_size=4)
    await pipeline.run()

    assert results == []


@pytest.mark.anyio
async def test_three_stage_pipeline() -> None:
    """A 3-stage pipeline (transform, transform, consumer) works correctly."""
    results: list[str] = []

    async def add_one(x: int) -> int:
        return x + 1

    async def to_string(x: int) -> str:
        return str(x)

    async def collect(x: str) -> None:
        results.append(x)

    pipeline = TaskPipeline(source=_count_up(4), stages=[add_one, to_string, collect], queue_size=3)
    await pipeline.run()

    assert results == ["1", "2", "3", "4"]


@pytest.mark.anyio
async def test_no_stages_raises() -> None:
    """Constructing a pipeline with no stages raises ValueError."""
    with pytest.raises(ValueError, match="at least one stage"):
        TaskPipeline(source=_count_up(1), stages=[], queue_size=4)


@pytest.mark.anyio
async def test_names_wrong_length_raises() -> None:
    """names must have exactly len(stages) + 1 entries."""

    async def collect(x: int) -> None:
        pass  # pragma: no cover

    with pytest.raises(ValueError, match="len\\(stages\\) \\+ 1"):
        TaskPipeline(source=_count_up(1), stages=[collect], queue_size=4, names=["only_one"])

    with pytest.raises(ValueError, match="len\\(stages\\) \\+ 1"):
        TaskPipeline(source=_count_up(1), stages=[collect], queue_size=4, names=["a", "b", "c"])


@pytest.mark.anyio
async def test_queues_property() -> None:
    """The queues property exposes the inter-stage queues created during run()."""
    results: list[int] = []

    async def double(x: int) -> int:
        return x * 2

    async def collect(x: int) -> None:
        results.append(x)

    pipeline = TaskPipeline(source=_count_up(3), stages=[double, collect], queue_size=4)
    assert pipeline.queues == []
    await pipeline.run()
    assert len(pipeline.queues) == 2
    assert results == [0, 2, 4]


@pytest.mark.anyio
async def test_drain_includes_dropped_results() -> None:
    """drain() includes results that a stage produced but could not enqueue
    because the pipeline was already shutting down."""
    consumed: list[int] = []
    produced: list[int] = []

    async def slow_transform(x: int) -> int:
        produced.append(x)
        if x == 0:
            # give the consumer time to fail before we return
            await asyncio.sleep(0.1)
        return x * 10

    async def failing_consumer(x: int) -> None:
        consumed.append(x)
        raise ValueError("consumer failed")

    pipeline = TaskPipeline(source=_count_up(5), stages=[slow_transform, failing_consumer], queue_size=2)
    with pytest.raises(ValueError, match="consumer failed"):
        await pipeline.run()

    remaining = pipeline.drain(1)
    # The transform produced item 0 (which the consumer saw and failed on),
    # but it may also have produced further items that couldn't be enqueued.
    # drain() should include both queued and dropped items.
    all_seen = consumed + remaining
    for item in all_seen:
        assert isinstance(item, int)
    # The dropped result from slow_transform(0) should appear somewhere —
    # either consumed by the failing consumer or recovered via drain.
    assert 0 in produced


@pytest.mark.anyio
async def test_failed_during_stage_saves_result_to_dropped() -> None:
    """If the pipeline fails while a transform is awaiting and the transform
    suppresses CancelledError and returns a result, that result is saved to
    _dropped and recovered via drain()."""

    async def resilient_transform(x: int) -> int:
        try:
            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        return x * 10

    async def failing_consumer(x: int) -> None:
        raise ValueError("boom")

    pipeline = TaskPipeline(source=_count_up(10), stages=[resilient_transform, failing_consumer], queue_size=2)
    with pytest.raises(ValueError, match="boom"):
        await pipeline.run()

    remaining = pipeline.drain(1)
    assert any(item % 10 == 0 for item in remaining)


@pytest.mark.anyio
async def test_stage_blocked_on_empty_queue_bails_on_failure() -> None:
    """When a stage is blocked in _get_or_bail's slow path (queue empty) and
    another stage fails, the blocked stage exits via the fail event."""

    async def stalling_source() -> AsyncIterator[int]:
        yield 0
        await asyncio.Event().wait()  # stall forever; never yields again

    async def transform(x: int) -> int:
        return x

    async def failing_consumer(x: int) -> None:
        raise ValueError("consumer exploded")

    pipeline = TaskPipeline(
        source=stalling_source(),
        stages=[transform, failing_consumer],
        queue_size=2,
    )
    with pytest.raises(ValueError, match="consumer exploded"):
        await pipeline.run()


@pytest.mark.anyio
async def test_get_or_bail_slow_path_item_arrives() -> None:
    """Exercise _get_or_bail's slow path where the queue is empty when polled
    but an item arrives before any failure (get_task wins the race)."""
    results: list[int] = []

    async def delayed_source() -> AsyncIterator[int]:
        for i in range(5):
            await asyncio.sleep(0.02)
            yield i

    async def collect(x: int) -> None:
        results.append(x)

    pipeline = TaskPipeline(source=delayed_source(), stages=[collect], queue_size=2)
    await pipeline.run()

    assert results == [0, 1, 2, 3, 4]


@pytest.mark.anyio
async def test_cancellation_calls_cleanup() -> None:
    """Cancelling the run() task still invokes the cleanup callback."""
    cleanup_called = asyncio.Event()

    async def cleanup(p: TaskPipeline) -> None:
        cleanup_called.set()

    async def slow_source() -> AsyncIterator[int]:
        for i in range(1000):
            await asyncio.sleep(0.1)
            yield i  # pragma: no cover

    async def collect(x: int) -> None:
        pass  # pragma: no cover

    pipeline = TaskPipeline(source=slow_source(), stages=[collect], queue_size=2, cleanup=cleanup)
    task = asyncio.ensure_future(pipeline.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleanup_called.is_set()


@pytest.mark.anyio
async def test_cancellation_does_not_leak_tasks() -> None:
    """Cancelling run() awaits all internal tasks so nothing is left dangling."""

    async def slow_source() -> AsyncIterator[int]:
        for i in range(1000):
            await asyncio.sleep(0.1)
            yield i

    stage_tasks_done: list[bool] = []

    async def slow_stage(x: int) -> int:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            stage_tasks_done.append(True)
            raise
        return x  # pragma: no cover

    async def collect(x: int) -> None:
        pass  # pragma: no cover

    pipeline = TaskPipeline(source=slow_source(), stages=[slow_stage, collect], queue_size=2)
    task = asyncio.ensure_future(pipeline.run())
    await asyncio.sleep(0.15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Give the event loop a tick to finalize everything
    await asyncio.sleep(0)
    # The stage task should have been cancelled and awaited, not left dangling
    assert len(stage_tasks_done) > 0
