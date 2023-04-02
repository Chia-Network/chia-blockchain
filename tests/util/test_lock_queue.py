from __future__ import annotations

import asyncio
import enum
import logging
import random
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import anyio
import pytest

from chia.full_node.lock_queue import LockQueue, NestedLockUnsupportedError
from chia.simulator.time_out_assert import adjusted_timeout

log = logging.getLogger(__name__)


class LockPriority(enum.IntEnum):
    # lower values are higher priority
    low = 2
    medium = 1
    high = 0


lock_priorities = list(LockPriority)


class RequestNotCompleteError(Exception):
    pass


@pytest.mark.asyncio
async def test_lock_queue():
    queue = LockQueue[LockPriority]()

    async def slow_func():
        for i in range(100):
            await asyncio.sleep(0.01)

    async def kind_of_slow_func():
        for i in range(100):
            await asyncio.sleep(0.001)

    async def do_high():
        for i in range(10):
            log.warning("Starting high")
            t1 = time.time()
            async with queue.acquire(priority=LockPriority.high):
                log.warning(f"Spend {time.time() - t1} waiting for high")
                await slow_func()

    async def do_low(i: int):
        log.warning(f"Starting low {i}")
        t1 = time.time()
        async with queue.acquire(priority=LockPriority.low):
            log.warning(f"Spend {time.time() - t1} waiting for low {i}")
            await kind_of_slow_func()

    h = asyncio.create_task(do_high())
    l_tasks = []
    for i in range(50):
        l_tasks.append(asyncio.create_task(do_low(i)))

    winner = None

    while True:
        if h.done():
            if winner is None:
                winner = "h"

        l_finished = True
        for t in l_tasks:
            if not t.done():
                l_finished = False
        if l_finished and winner is None:
            winner = "l"
        if l_finished and h.done():
            break
        await asyncio.sleep(1)
    assert winner == "h"


@dataclass
class Request:
    # TODO: is the ID unneeded?
    id: str
    priority: LockPriority
    acquisition_time: Optional[float] = None
    release_time: Optional[float] = None
    clock: Callable[[], float] = time.monotonic
    # TODO: done may not be needed
    done: bool = False
    completed: bool = False

    def __lt__(self, other: Request) -> bool:
        if self.acquisition_time is None or other.acquisition_time is None:
            raise RequestNotCompleteError()

        return self.acquisition_time < other.acquisition_time

    async def acquire(
        self,
        queue: LockQueue[LockPriority],
        queued_callback: Callable[[], object],
        wait_for: asyncio.Event,
    ) -> None:
        if self.done:
            raise Exception("attempting to reacquire a request")

        try:
            async with queue.acquire(priority=self.priority, queued_callback=queued_callback):
                self.acquisition_time = self.clock()
                await wait_for.wait()
                self.release_time = self.clock()
        finally:
            self.done = True

        self.completed = True

    def before(self, other: Request) -> bool:
        if self.release_time is None or other.acquisition_time is None:
            raise RequestNotCompleteError()

        return self.release_time < other.acquisition_time


@dataclass(frozen=True)
class OrderCase:
    requests: List[Request]
    expected_acquisitions: List[str]


@pytest.mark.parametrize(
    argnames="case",
    argvalues=[
        # request high to low
        OrderCase(
            requests=[
                Request(id="high", priority=LockPriority.high),
                Request(id="medium", priority=LockPriority.medium),
                Request(id="low", priority=LockPriority.low),
            ],
            expected_acquisitions=["high", "medium", "low"],
        ),
        # request low to high
        OrderCase(
            requests=[
                Request(id="low", priority=LockPriority.low),
                Request(id="medium", priority=LockPriority.medium),
                Request(id="high", priority=LockPriority.high),
            ],
            expected_acquisitions=["low", "high", "medium"],
        ),
        # request in mixed order
        OrderCase(
            requests=[
                Request(id="medium", priority=LockPriority.medium),
                Request(id="low", priority=LockPriority.low),
                Request(id="high", priority=LockPriority.high),
            ],
            expected_acquisitions=["medium", "high", "low"],
        ),
        # request with multiple of each
        OrderCase(
            requests=[
                Request(id="medium a", priority=LockPriority.medium),
                Request(id="low a", priority=LockPriority.low),
                Request(id="high a", priority=LockPriority.high),
                Request(id="medium b", priority=LockPriority.medium),
                Request(id="low b", priority=LockPriority.low),
                Request(id="high b", priority=LockPriority.high),
            ],
            expected_acquisitions=["medium a", "high a", "high b", "medium b", "low a", "low b"],
        ),
    ],
)
@pytest.mark.asyncio
async def test_order(case: OrderCase):
    queue = LockQueue[LockPriority]()

    random_instance = random.Random()
    random_instance.seed(a=0, version=2)

    tasks = await create_acquire_tasks_in_controlled_order(case.requests, queue)
    await asyncio.gather(*tasks)

    actual_acquisition_order = sorted(case.requests)

    assert actual_acquisition_order == expected_acquisition_order(requests=case.requests)
    assert sane(requests=case.requests)


def expected_acquisition_order(requests):
    first_request, *other_requests = requests
    return [
        first_request,
        *(request for priority in sorted(LockPriority) for request in other_requests if request.priority == priority),
    ]


@pytest.mark.asyncio
async def test_sequential_acquisitions():
    queue = LockQueue[LockPriority]()

    random_instance = random.Random()
    random_instance.seed(a=0, version=2)

    for _ in range(1000):
        with anyio.fail_after(delay=adjusted_timeout(timeout=10)):
            async with queue.acquire(priority=random_instance.choice(lock_priorities)):
                pass

    # just testing that we can get through a bunch of miscellaneous acquisitions


@pytest.mark.asyncio
async def test_nested_acquisition_raises():
    queue = LockQueue[LockPriority]()

    async with queue.acquire(priority=LockPriority.high):
        with pytest.raises(NestedLockUnsupportedError):
            async with queue.acquire(priority=LockPriority.high):
                pass


@pytest.mark.asyncio
async def test_cancellation_while_waiting():
    queue = LockQueue[LockPriority]()

    random_instance = random.Random()
    random_instance.seed(a=0, version=2)

    blocker_continue_event = asyncio.Event()
    blocker_acquired_event = asyncio.Event()

    async def block() -> None:
        async with queue.acquire(priority=LockPriority.high):
            blocker_acquired_event.set()
            await blocker_continue_event.wait()

    cancel_queued_event = asyncio.Event()

    async def to_be_cancelled() -> None:
        async with queue.acquire(priority=LockPriority.high, queued_callback=cancel_queued_event.set):
            assert False

    queued_after_queued_event = asyncio.Event()

    async def queued_after() -> None:
        async with queue.acquire(priority=LockPriority.high, queued_callback=queued_after_queued_event.set):
            pass

    block_task = asyncio.create_task(block())
    await blocker_acquired_event.wait()

    cancel_task = asyncio.create_task(to_be_cancelled())
    await cancel_queued_event.wait()

    queued_after_task = asyncio.create_task(queued_after())
    await queued_after_queued_event.wait()

    cancel_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await cancel_task

    blocker_continue_event.set()
    await block_task
    await queued_after_task

    # TODO: do something other than hanging for ever on a, well, a hang


# testing many repeatable randomization cases
@pytest.mark.parametrize(argnames="seed", argvalues=range(100), ids=lambda seed: f"random seed {seed}")
@pytest.mark.asyncio
async def test_retains_request_order_for_matching_priority(seed: int):
    queue = LockQueue[LockPriority]()

    random_instance = random.Random()
    random_instance.seed(a=seed, version=2)

    all_requests = [Request(id=str(index), priority=random_instance.choice(lock_priorities)) for index in range(1000)]

    tasks = await create_acquire_tasks_in_controlled_order(all_requests, queue)
    await asyncio.gather(*tasks)

    actual_acquisition_order = sorted(all_requests)

    assert actual_acquisition_order == expected_acquisition_order(requests=all_requests)
    assert sane(requests=all_requests)


def sane(requests: List[Request]):
    if any(not request.completed for request in requests):
        return False

    ordered = sorted(requests)
    return all(a.before(b) for a, b in zip(ordered, ordered[1:]))


async def create_acquire_tasks_in_controlled_order(requests: List[Request], queue: LockQueue[LockPriority]):
    tasks: List[asyncio.Task] = []
    release_event = asyncio.Event()

    for request in requests:
        queued_event = asyncio.Event()
        tasks.append(
            asyncio.create_task(request.acquire(queue=queue, queued_callback=queued_event.set, wait_for=release_event))
        )
        await queued_event.wait()

    release_event.set()

    return tasks
