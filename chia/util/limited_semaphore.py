from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import AsyncIterator

from typing_extensions import final


class LimitedSemaphoreFullError(Exception):
    def __init__(self) -> None:
        super().__init__("no waiting slot available")


@final
@dataclass
class LimitedSemaphore:
    _semaphore: asyncio.Semaphore
    _available_count: int

    @classmethod
    def create(cls, active_limit: int, waiting_limit: int) -> LimitedSemaphore:
        return cls(
            _semaphore=asyncio.Semaphore(active_limit),
            _available_count=active_limit + waiting_limit,
        )

    @contextlib.asynccontextmanager
    async def acquire(self) -> AsyncIterator[int]:
        if self._available_count < 1:
            raise LimitedSemaphoreFullError()

        self._available_count -= 1
        try:
            async with self._semaphore:
                yield self._available_count
        finally:
            self._available_count += 1
