from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Protocol, runtime_checkable

from typing_extensions import Self


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

    def __init__(self, max_workers: int, *, dedicated: int = 0, thread_name_prefix: str = "") -> None:
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
        for i in range(dedicated):
            name = f"{thread_name_prefix}dedicated-{i}" if thread_name_prefix else None
            t = threading.Thread(target=self._worker, args=(self._dedicated_queue,), name=name)
            t.start()
            self._threads.append(t)
        for i in range(max_workers - dedicated):
            name = f"{thread_name_prefix}{i}" if thread_name_prefix else None
            t = threading.Thread(target=self._worker, args=(self._general_queue,), name=name)
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
            item = _WorkItem(False, nice, seq, fn, args, kwargs, future)
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
            for _ in range(self._dedicated_count):
                seq = self._seq
                self._seq += 1
                self._dedicated_queue.put(_WorkItem(_sentinel=True, nice=(0,), seq=seq))
            for _ in range(len(self._threads) - self._dedicated_count):
                seq = self._seq
                self._seq += 1
                self._general_queue.put(_WorkItem(_sentinel=True, nice=(0,), seq=seq))
        for t in self._threads:
            t.join()

    @staticmethod
    def _worker(q: queue.PriorityQueue[_WorkItem]) -> None:
        while True:
            item = q.get()
            if item.fn is None:
                return
            if not item._claim.acquire(blocking=False):
                continue
            assert item.future is not None
            if not item.future.set_running_or_notify_cancel():
                continue
            try:
                result = item.fn(*item.args, **item.kwargs)
                item.future.set_result(result)
            except BaseException as e:
                item.future.set_exception(e)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.shutdown()
