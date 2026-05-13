# Package: utils

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Executor, Future
from typing import Any, TypeVar

_T = TypeVar("_T")


class InlineExecutor(Executor):
    _closing: bool = False

    def submit(self, fn: Callable[..., _T], *args: Any, **kwargs: Any) -> Future[_T]:  # type: ignore
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

    def shutdown(self, wait: bool = True) -> None:  # type: ignore[override]
        self._closing = True

    def close(self) -> None:
        self.shutdown()
