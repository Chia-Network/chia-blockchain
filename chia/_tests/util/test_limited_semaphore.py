from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from chia.util.limited_semaphore import LimitedSemaphore, LimitedSemaphoreFullError


@pytest.mark.anyio
async def test_stuff() -> None:
    active_limit = 2
    waiting_limit = 4
    total_limit = active_limit + waiting_limit
    beyond_limit = 3
    semaphore = LimitedSemaphore.create(active_limit=active_limit, waiting_limit=waiting_limit)
    finish_event = asyncio.Event()

    async def acquire(entered_event: Optional[asyncio.Event] = None) -> None:
        async with semaphore.acquire():
            assert entered_event is not None
            entered_event.set()
            await finish_event.wait()

    entered_events = [asyncio.Event() for _ in range(active_limit)]
    waiting_events = [asyncio.Event() for _ in range(waiting_limit)]
    failed_events = [asyncio.Event() for _ in range(beyond_limit)]

    entered_tasks = [asyncio.create_task(acquire(entered_event=event)) for event in entered_events]
    waiting_tasks = [asyncio.create_task(acquire(entered_event=event)) for event in waiting_events]

    await asyncio.gather(*(event.wait() for event in entered_events))
    assert all(event.is_set() for event in entered_events)
    assert all(not event.is_set() for event in waiting_events)

    assert semaphore._available_count == 0

    failure_tasks = [asyncio.create_task(acquire()) for _ in range(beyond_limit)]

    failure_results = await asyncio.gather(*failure_tasks, return_exceptions=True)
    assert [str(error) for error in failure_results] == [str(LimitedSemaphoreFullError())] * beyond_limit
    assert all(not event.is_set() for event in failed_events)

    assert semaphore._available_count == 0

    finish_event.set()
    success_results = await asyncio.gather(*entered_tasks, *waiting_tasks)
    assert all(event.is_set() for event in waiting_events)
    assert success_results == [None] * total_limit

    assert semaphore._available_count == total_limit
