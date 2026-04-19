from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Protocol, runtime_checkable

from typing_extensions import Self

log = logging.getLogger(__name__)


class _SupportsLessThan(Protocol):
    def __lt__(self, other: Self, /) -> bool: ...


@runtime_checkable
class Executor(Protocol):
    def run_in_loop(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        nice: _SupportsLessThan = (0,),
        dedicated: bool = False,
        **kwargs: Any,
    ) -> asyncio.Future[Any]: ...

    def shutdown(self, wait: bool = True) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None: ...


@dataclass(order=True)
class _WorkItem:
    """Wraps a callable for priority queue ordering.

    Fields participate in comparison in declaration order.  ``_sentinel``
    sorts first: since ``False < True``, real work items always come before
    shutdown sentinels regardless of ``nice`` values.  Among real items,
    lower ``nice`` runs first (like Unix niceness), with ``seq`` breaking
    ties in FIFO order.  A sentinel is represented by ``fn is None``.
    """

    _sentinel: bool
    nice: _SupportsLessThan
    seq: int
    fn: Callable[..., Any] | None = field(compare=False, default=None)
    args: tuple[Any, ...] = field(compare=False, default=())
    kwargs: dict[str, Any] = field(compare=False, default_factory=dict)
    future: Future[Any] | None = field(compare=False, default=None)
    enqueue_time: float = field(compare=False, default=0.0)
    _claim: threading.Lock = field(compare=False, default_factory=threading.Lock)


class PriorityThreadPoolExecutor:
    """Thread pool with priority ordering and optional dedicated threads.

    Dedicated threads only pull from the dedicated queue and are never
    occupied by non-dedicated work, guaranteeing they are available (or
    will be shortly) when dedicated work arrives.

    Jobs submitted with ``dedicated=True`` are posted to *both* queues
    so that general threads can also help with dedicated work.  This is
    important during long sync where multiple FullBlocks are validated
    in parallel and we want to utilize all cores.  The duplicate queue
    entry is resolved cheaply: each thread calls
    ``set_running_or_notify_cancel()`` on the shared Future, and only the
    first thread to claim it runs the job; the other skips it.

    We considered alternatives (condition variables, semaphores, separate
    queues without cross-posting) but they all have drawbacks.  A shared
    condition variable with ``notify_all()`` causes thundering herd wake-ups,
    and a dedicated thread woken for a non-dedicated job must re-signal
    without a clean way to target a general thread.  Separate queues
    without cross-posting would prevent general threads from helping with
    dedicated work.  The dual-post approach lets every thread sleep
    efficiently on a blocking ``queue.get()`` while still allowing all
    threads to contribute to dedicated work.
    """

    def __init__(
        self, max_workers: int, *, dedicated: int = 0, thread_name_prefix: str = "", instrument: bool = False
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if dedicated < 0 or dedicated >= max_workers:
            raise ValueError("dedicated must be >= 0 and < max_workers")
        self._general_queue: queue.PriorityQueue[_WorkItem] = queue.PriorityQueue()
        self._dedicated_queue: queue.PriorityQueue[_WorkItem] = queue.PriorityQueue()
        self._dedicated_count = dedicated
        self._seq = 0
        self._shutdown = False
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

        self._instrument = instrument
        self._stats_lock = threading.Lock()
        self._retired_dedicated = 0
        self._retired_general = 0
        self._stop_instrument = threading.Event()

        for i in range(dedicated):
            name = f"{thread_name_prefix}dedicated-{i}" if thread_name_prefix else None
            t = threading.Thread(target=self._worker, args=(self._dedicated_queue, True), name=name)
            t.start()
            self._threads.append(t)
        for i in range(max_workers - dedicated):
            name = f"{thread_name_prefix}{i}" if thread_name_prefix else None
            t = threading.Thread(target=self._worker, args=(self._general_queue, False), name=name)
            t.start()
            self._threads.append(t)

        if instrument:
            t = threading.Thread(
                target=self._instrument_loop, name=f"{thread_name_prefix}instrument" if thread_name_prefix else None
            )
            t.start()
            self._threads.append(t)

    def submit(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        nice: _SupportsLessThan = (0,),
        dedicated: bool = False,
        **kwargs: Any,
    ) -> Future[Any]:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("cannot submit to a shut-down pool")
            future: Future[Any] = Future()
            seq = self._seq
            self._seq += 1
            now = time.monotonic() if self._instrument else 0.0
            item = _WorkItem(False, nice, seq, fn, args, kwargs, future, now)
            self._general_queue.put(item)
            if dedicated and self._dedicated_count > 0:
                self._dedicated_queue.put(item)
            return future

    def run_in_loop(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        nice: _SupportsLessThan = (0,),
        dedicated: bool = False,
        **kwargs: Any,
    ) -> asyncio.Future[Any]:
        return asyncio.wrap_future(self.submit(fn, *args, nice=nice, dedicated=dedicated, **kwargs))

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            self._shutdown = True
            self._stop_instrument.set()
            for _ in range(self._dedicated_count):
                seq = self._seq
                self._seq += 1
                self._dedicated_queue.put(_WorkItem(_sentinel=True, nice=(0,), seq=seq))
            for _ in range(len(self._threads) - self._dedicated_count - (1 if self._instrument else 0)):
                seq = self._seq
                self._seq += 1
                self._general_queue.put(_WorkItem(_sentinel=True, nice=(0,), seq=seq))
        for t in self._threads:
            t.join()

    def _worker(self, q: queue.PriorityQueue[_WorkItem], is_dedicated: bool) -> None:
        while True:
            item = q.get()
            if item.fn is None:
                return
            if not item._claim.acquire(blocking=False):
                continue
            assert item.future is not None
            if not item.future.set_running_or_notify_cancel():
                continue
            if self._instrument:
                with self._stats_lock:
                    if is_dedicated:
                        self._retired_dedicated += 1
                    else:
                        self._retired_general += 1
            try:
                result = item.fn(*item.args, **item.kwargs)
                item.future.set_result(result)
            except BaseException as e:
                item.future.set_exception(e)

    @staticmethod
    def _oldest_pending_wait(q: queue.PriorityQueue[_WorkItem], now: float) -> float:
        """Return the wait time of the oldest still-pending item in *q*."""
        max_wait = 0.0
        with q.mutex:
            for item in q.queue:
                if item._sentinel or item.enqueue_time == 0.0:
                    continue
                assert item.future is not None
                if not item.future.running() and not item.future.done():
                    max_wait = max(max_wait, now - item.enqueue_time)
        return max_wait

    def _instrument_loop(self) -> None:
        prev_retired_ded = 0
        prev_retired_gen = 0
        while not self._stop_instrument.wait(10):
            now = time.monotonic()
            with self._stats_lock:
                retired_ded = self._retired_dedicated
                retired_gen = self._retired_general
            if retired_ded == prev_retired_ded and retired_gen == prev_retired_gen:
                continue
            prev_retired_ded = retired_ded
            prev_retired_gen = retired_gen
            pending_ded = self._oldest_pending_wait(self._dedicated_queue, now)
            pending_gen = self._oldest_pending_wait(self._general_queue, now)
            log.info(
                f"thread pool: "
                f"Queue: {self._dedicated_queue.qsize()}, {self._general_queue.qsize()} "
                f"Retired: {retired_ded}, {retired_gen} "
                f"Pending: {pending_ded:.1f}s, {pending_gen:.1f}s"
            )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.shutdown()
