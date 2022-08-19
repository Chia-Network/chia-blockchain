from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Optional, Type

from filelock import BaseFileLock, FileLock, Timeout
from typing_extensions import final


class LockfileError(Exception):
    pass


@final
@dataclass(frozen=True)
class Lockfile:
    _lock: BaseFileLock
    timeout: float
    poll_interval: float

    @classmethod
    def create(cls, path: Path, timeout: float = -1, poll_interval: float = 0.05) -> Lockfile:
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(_lock=FileLock(path.with_name(path.name + ".lock")), timeout=timeout, poll_interval=poll_interval)

    def __enter__(self) -> Lockfile:
        self.acquire(timeout=self.timeout, poll_interval=self.poll_interval)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.release()

    def acquire(self, timeout: float, poll_interval: float) -> None:
        try:
            self._lock.acquire(timeout=timeout, poll_interval=poll_interval)
        except Timeout as e:
            raise LockfileError(e) from e

    def release(self) -> None:
        self._lock.release()
