from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any


class TaskPipeline:
    """
    An N-stage async pipeline that connects an async-iterator source to a
    chain of per-item async callables via bounded queues.

    The source (an AsyncIterator) produces items that flow through each stage.
    Each stage is called once per item and may return a value to forward
    downstream, or None to skip/filter the item. The last stage is a pure
    consumer (its return value is discarded).

    The pipeline manages internal queues, back-pressure, and graceful shutdown
    on failure (sentinel propagation, no task cancellation).
    """

    def __init__(
        self,
        source: AsyncIterator[Any],
        stages: list[Callable[[Any], Awaitable[Any]]],
        queue_size: int = 10,
        names: list[str] | None = None,
        log: logging.Logger | None = None,
        cleanup: Callable[[TaskPipeline], Awaitable[None]] | None = None,
    ) -> None:
        if len(stages) == 0:
            raise ValueError("pipeline requires at least one stage")
        if names is not None and len(names) != len(stages) + 1:
            raise ValueError("names must have len(stages) + 1 entries (source + each stage)")
        self._source = source
        self._stages = stages
        self._queue_size = queue_size
        self._names = names
        self._log = log
        self._cleanup = cleanup
        self._queues: list[asyncio.Queue[Any]] = []
        # Results produced by a stage after the pipeline began shutting down,
        # which could not be enqueued. Recovered via drain().
        self._dropped: list[list[Any]] = []
        self._failed = asyncio.Event()
        self._exception: BaseException | None = None

    @property
    def queues(self) -> list[asyncio.Queue[Any]]:
        return self._queues

    def drain(self, queue_index: int) -> list[Any]:
        """Drain all non-sentinel items remaining in the queue at the given
        index, plus any results that a stage produced but could not enqueue
        because the pipeline was shutting down.

        Only indices 1 .. len(stages)-1 are useful: _dropped[0] is never
        written to (the feeder doesn't use it), and there is no queue after
        the last stage."""
        items: list[Any] = []
        q = self._queues[queue_index]
        while not q.empty():
            item = q.get_nowait()
            if item is not None:
                items.append(item)
        items.extend(self._dropped[queue_index])
        self._dropped[queue_index].clear()
        return items

    async def run(self) -> None:
        """Run the pipeline to completion. Re-raises the first stage exception."""
        self._queues = [asyncio.Queue(maxsize=self._queue_size) for _ in range(len(self._stages))]
        self._dropped = [[] for _ in range(len(self._stages))]
        self._failed.clear()
        self._exception = None

        tasks = [asyncio.ensure_future(self._run_feeder())]
        tasks.extend(asyncio.ensure_future(self._run_stage(i)) for i in range(len(self._stages)))

        try:
            all_done: asyncio.Task[Any] = asyncio.ensure_future(asyncio.gather(*tasks, return_exceptions=True))
            fail_wait: asyncio.Task[Any] = asyncio.ensure_future(self._failed.wait())
            try:
                done, _ = await asyncio.wait({all_done, fail_wait}, return_when=asyncio.FIRST_COMPLETED)
                if all_done not in done:
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                fail_wait.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await fail_wait
                all_done.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await all_done
        except asyncio.CancelledError:
            self._failed.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            if self._cleanup is not None:
                await self._cleanup(self)

        if self._exception is not None:
            raise self._exception

    async def _put_or_bail(self, queue: asyncio.Queue[Any], item: object) -> bool:
        """Put item on queue. Returns False if the pipeline has failed (item discarded)."""
        if self._failed.is_set():
            return False
        try:
            queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            pass
        # Slow path: queue is full, race between put completing and pipeline failure.
        put_task = asyncio.ensure_future(queue.put(item))
        fail_task = asyncio.ensure_future(self._failed.wait())
        try:
            done, _ = await asyncio.wait({put_task, fail_task}, return_when=asyncio.FIRST_COMPLETED)
            if put_task in done:
                put_task.result()
                return True
            # Defensive: run() cancels tasks on failure before this
            # await can observe fail_task completing, so this path
            # is not reachable in practice.
            else:  # pragma: no cover
                put_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await put_task
                return False
        finally:
            fail_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await fail_task

    async def _get_or_bail(self, queue: asyncio.Queue[Any]) -> tuple[bool, Any]:
        """Get item from queue. Returns (False, None) if the pipeline has failed."""
        if self._failed.is_set():
            return False, None
        try:
            item = queue.get_nowait()
            return True, item
        except asyncio.QueueEmpty:
            pass
        # Slow path: queue is empty, race between get completing and pipeline failure.
        get_task = asyncio.ensure_future(queue.get())
        fail_task = asyncio.ensure_future(self._failed.wait())
        try:
            done, _ = await asyncio.wait({get_task, fail_task}, return_when=asyncio.FIRST_COMPLETED)
            if get_task in done:
                return True, get_task.result()
            # Defensive: run() cancels tasks on failure before this
            # await can observe fail_task completing, so this path
            # is not reachable in practice.
            else:  # pragma: no cover
                get_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await get_task
                return False, None
        finally:
            fail_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await fail_task

    async def _run_feeder(self) -> None:
        output_queue = self._queues[0]
        try:
            async for item in self._source:
                if not await self._put_or_bail(output_queue, item):
                    return
        except Exception as e:
            if self._names is not None and self._log is not None:
                self._log.exception("Exception %s", self._names[0])
            if self._exception is None:
                self._exception = e
            self._failed.set()
        finally:
            # Propagate sentinel downstream. Uses _put_or_bail so that on
            # normal completion it waits for space (downstream is alive), and
            # on failure it bails immediately (downstream will see _failed).
            await self._put_or_bail(output_queue, None)

    async def _run_stage(self, idx: int) -> None:
        input_queue = self._queues[idx]
        output_queue = self._queues[idx + 1] if idx < len(self._stages) - 1 else None
        try:
            while True:
                ok, item = await self._get_or_bail(input_queue)
                if not ok or item is None:
                    return
                result = await self._stages[idx](item)
                if self._failed.is_set():
                    if output_queue is not None and result is not None:
                        self._dropped[idx + 1].append(result)
                    return
                if output_queue is None or result is None:
                    continue
                # Defensive: run() cancels tasks on failure before
                # _put_or_bail can return False from its slow path,
                # so this branch is not reachable in practice.
                if not await self._put_or_bail(output_queue, result):  # pragma: no cover
                    self._dropped[idx + 1].append(result)
                    return
        except Exception as e:
            if self._names is not None and self._log is not None:
                self._log.exception("Exception %s", self._names[idx + 1])
            if self._exception is None:
                self._exception = e
            self._failed.set()
        finally:
            if output_queue is not None:
                await self._put_or_bail(output_queue, None)
