from __future__ import annotations

import asyncio

import pytest

from chia.util.limited_semaphore import LimitedSemaphore, LimitedSemaphoreFullError
from chia.util.task_referencer import create_referenced_task


@pytest.mark.anyio
async def test_tracking_set_cleanup_on_semaphore_full() -> None:
    """Verify that a tracking set entry is not leaked when LimitedSemaphoreFullError is raised.

    Reproduces the pattern in new_compact_vdf / respond_compact_proof_of_time
    where a name is added to compact_vdf_requests before acquiring the semaphore.
    Without cleanup in the except block, the entry would be permanently leaked.
    """
    semaphore = LimitedSemaphore.create(active_limit=1, waiting_limit=0)
    tracking_set: set[str] = set()
    finish_event = asyncio.Event()

    async def hold_semaphore() -> None:
        async with semaphore.acquire():
            await finish_event.wait()

    holder = create_referenced_task(hold_semaphore())
    await asyncio.sleep(0)

    for i in range(5):
        name = f"entry-{i}"
        tracking_set.add(name)
        try:
            async with semaphore.acquire():
                try:
                    pass
                finally:
                    tracking_set.discard(name)
        except LimitedSemaphoreFullError:
            tracking_set.discard(name)

    assert len(tracking_set) == 0, f"Leaked entries: {tracking_set}"

    finish_event.set()
    await holder

    # Verify semaphore is fully released
    assert semaphore._available_count == 1


@pytest.mark.anyio
async def test_tracking_set_cleanup_on_success() -> None:
    """Verify the tracking set is cleaned up on the normal (successful acquire) path."""
    semaphore = LimitedSemaphore.create(active_limit=2, waiting_limit=2)
    tracking_set: set[str] = set()

    for i in range(4):
        name = f"entry-{i}"
        tracking_set.add(name)
        try:
            async with semaphore.acquire():
                try:
                    pass
                finally:
                    tracking_set.discard(name)
        except LimitedSemaphoreFullError:
            tracking_set.discard(name)

    assert len(tracking_set) == 0, f"Leaked entries: {tracking_set}"


@pytest.mark.anyio
async def test_stuff() -> None:
    active_limit = 2
    waiting_limit = 4
    total_limit = active_limit + waiting_limit
    beyond_limit = 3
    semaphore = LimitedSemaphore.create(active_limit=active_limit, waiting_limit=waiting_limit)
    finish_event = asyncio.Event()

    async def acquire(entered_event: asyncio.Event | None = None) -> None:
        async with semaphore.acquire():
            assert entered_event is not None
            entered_event.set()
            await finish_event.wait()

    entered_events = [asyncio.Event() for _ in range(active_limit)]
    waiting_events = [asyncio.Event() for _ in range(waiting_limit)]
    failed_events = [asyncio.Event() for _ in range(beyond_limit)]

    entered_tasks = [create_referenced_task(acquire(entered_event=event)) for event in entered_events]
    waiting_tasks = [create_referenced_task(acquire(entered_event=event)) for event in waiting_events]

    await asyncio.gather(*(event.wait() for event in entered_events))
    assert all(event.is_set() for event in entered_events)
    assert all(not event.is_set() for event in waiting_events)

    assert semaphore._available_count == 0

    failure_tasks = [create_referenced_task(acquire()) for _ in range(beyond_limit)]

    failure_results = await asyncio.gather(*failure_tasks, return_exceptions=True)
    assert [str(error) for error in failure_results] == [str(LimitedSemaphoreFullError())] * beyond_limit
    assert all(not event.is_set() for event in failed_events)

    assert semaphore._available_count == 0

    finish_event.set()
    success_results = await asyncio.gather(*entered_tasks, *waiting_tasks)
    assert all(event.is_set() for event in waiting_events)
    assert success_results == [None] * total_limit

    assert semaphore._available_count == total_limit
