from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, TypeVar

from chia.util.priority_thread_pool_executor import PriorityThreadPoolExecutor

_T = TypeVar("_T")


class InlineExecutor(PriorityThreadPoolExecutor):
    _closing: bool = False

    def __init__(self) -> None:
        # Because jobs run in the caller we don't need any of the pool's
        # threads or queues.
        return

    def submit(self, fn: Callable[..., _T], *args: Any, **kwargs: Any) -> Future[_T]:  # type: ignore[override]
        if self._closing:
            raise RuntimeError("executor shutting down")

        f: Future[_T] = Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except BaseException as e:  # lgtm[py/catch-base-exception]
            f.set_exception(e)
        return f

    def run_in_loop(
        self, fn: Callable[..., Any], /, *args: Any, nice: Any = (0,), dedicated: bool = False, **kwargs: Any
    ) -> asyncio.Future[Any]:
        return asyncio.wrap_future(self.submit(fn, *args, **kwargs))

    def shutdown(self, wait: bool = True) -> None:
        self._closing = True

    def close(self) -> None:
        self.shutdown()
