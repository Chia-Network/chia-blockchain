from __future__ import annotations

from concurrent.futures import Executor, Future
from typing import Callable, TypeVar

_T = TypeVar("_T")


class InlineExecutor(Executor):
    _closing: bool = False

    def submit(self, fn: Callable[..., _T], *args, **kwargs) -> Future[_T]:  # type: ignore
        if self._closing:
            raise RuntimeError("executor shutting down")

        f: Future[_T] = Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except BaseException as e:  # lgtm[py/catch-base-exception]
            f.set_exception(e)
        return f

    def close(self) -> None:
        self._closing = True
