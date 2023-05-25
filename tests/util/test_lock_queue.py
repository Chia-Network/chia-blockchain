from __future__ import annotations

import asyncio
import enum
import itertools
import logging
import random
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import anyio
import pytest

from chia.full_node.lock_queue import LockQueue, NestedLockUnsupportedError
from chia.simulator.time_out_assert import adjusted_timeout
from tests.util.misc import Marks, datacases

log = logging.getLogger(__name__)


class LockPriority(enum.IntEnum):
    # lower values are higher priority
    low = 3
    # skipping 2 for testing
    high = 0
    # out of order for testing
    medium = 1


lock_priorities = list(LockPriority)


class RequestNotCompleteError(Exception):
    pass


class TestLockQueue:
    @pytest.mark.asyncio
    async def test_lock_queue(self):
        queue = await LockQueue.create(priority_type=LockPriority)

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


# This is used instead of time to have more determinism between platforms
# and specifically to avoid low resolution timers on Windows that can
# result in multiple events having the same time stamps.
counter = itertools.count()


@dataclass
class Request:
    # TODO: is the ID unneeded?
    id: str
    priority: LockPriority
    acquisition_order: Optional[int] = None
    release_order: Optional[int] = None
    order_counter: Callable[[], int] = counter.__next__
    # TODO: done may not be needed
    done: bool = False
    completed: bool = False

    def __lt__(self, other: Request) -> bool:
        if self.acquisition_order is None or other.acquisition_order is None:
            raise RequestNotCompleteError()

        return self.acquisition_order < other.acquisition_order

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
                self.acquisition_order = self.order_counter()
                await wait_for.wait()
                self.release_order = self.order_counter()
        finally:
            self.done = True

        self.completed = True

    def before(self, other: Request) -> bool:
        if self.release_order is None or other.acquisition_order is None:
            raise RequestNotCompleteError()

        return self.release_order < other.acquisition_order


@dataclass(frozen=True)
class OrderCase:
    requests: List[Request]
    expected_acquisitions: List[str]


@dataclass
class ComparisonCase:
    id: str
    self: Request
    other: Request
    marks: Marks = ()


@datacases(
    ComparisonCase(
        id="self incomplete",
        self=Request(id="self", priority=LockPriority.low),
        other=Request(id="other", priority=LockPriority.low, acquisition_order=0, release_order=0),
    ),
    ComparisonCase(
        id="other incomplete",
        self=Request(id="self", priority=LockPriority.low, acquisition_order=0, release_order=0),
        other=Request(id="other", priority=LockPriority.low),
    ),
    ComparisonCase(
        id="both incomplete",
        self=Request(id="self", priority=LockPriority.low),
        other=Request(id="other", priority=LockPriority.low),
    ),
)
@pytest.mark.parametrize(argnames="method", argvalues=[Request.__lt__, Request.before])
def test_comparisons_fail_for_incomplete_requests(
    case: ComparisonCase, method: Callable[[Request, Request], bool]
) -> None:
    with pytest.raises(RequestNotCompleteError):
        method(case.self, case.other)


@pytest.mark.asyncio
async def test_reacquisition_fails() -> None:
    queue = await LockQueue.create(priority_type=LockPriority)
    request = Request(id="again!", priority=LockPriority.low)
    event = asyncio.Event()
    event.set()

    await request.acquire(queue=queue, queued_callback=lambda: None, wait_for=event)

    with pytest.raises(Exception):
        await request.acquire(queue=queue, queued_callback=lambda: None, wait_for=event)


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
    queue = await LockQueue.create(priority_type=LockPriority)

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
    queue = await LockQueue.create(priority_type=LockPriority)

    random_instance = random.Random()
    random_instance.seed(a=0, version=2)

    for _ in range(1000):
        with anyio.fail_after(delay=adjusted_timeout(timeout=10)):
            async with queue.acquire(priority=random_instance.choice(lock_priorities)):
                pass

    # just testing that we can get through a bunch of miscellaneous acquisitions


@pytest.mark.asyncio
async def test_nested_acquisition_raises():
    queue = await LockQueue.create(priority_type=LockPriority)

    async with queue.acquire(priority=LockPriority.high):
        with pytest.raises(NestedLockUnsupportedError):
            async with queue.acquire(priority=LockPriority.high):
                # No coverage required since we're testing that this is not reached
                assert False  # pragma: no cover


async def to_be_cancelled(queue: LockQueue, event: asyncio.Event) -> None:
    async with queue.acquire(priority=LockPriority.high, queued_callback=event.set):
        assert False


@pytest.mark.asyncio
async def test_to_be_cancelled_fails_if_not_cancelled():
    queue = await LockQueue.create(priority_type=LockPriority)
    event = asyncio.Event()

    with pytest.raises(AssertionError):
        await to_be_cancelled(queue=queue, event=event)


@pytest.mark.asyncio
async def test_cancellation_while_waiting():
    queue = await LockQueue.create(priority_type=LockPriority)

    random_instance = random.Random()
    random_instance.seed(a=0, version=2)

    blocker_continue_event = asyncio.Event()
    blocker_acquired_event = asyncio.Event()

    async def block() -> None:
        async with queue.acquire(priority=LockPriority.high):
            blocker_acquired_event.set()
            await blocker_continue_event.wait()

    cancel_queued_event = asyncio.Event()

    queued_after_queued_event = asyncio.Event()

    async def queued_after() -> None:
        async with queue.acquire(priority=LockPriority.high, queued_callback=queued_after_queued_event.set):
            pass

    block_task = asyncio.create_task(block())
    await blocker_acquired_event.wait()

    cancel_task = asyncio.create_task(to_be_cancelled(queue=queue, event=cancel_queued_event))
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
    queue = await LockQueue.create(priority_type=LockPriority)

    random_instance = random.Random()
    random_instance.seed(a=seed, version=2)

    all_requests = [Request(id=str(index), priority=random_instance.choice(lock_priorities)) for index in range(1000)]

    tasks = await create_acquire_tasks_in_controlled_order(all_requests, queue)
    await asyncio.gather(*tasks)

    actual_acquisition_order = sorted(all_requests)

    assert actual_acquisition_order == expected_acquisition_order(requests=all_requests)
    assert sane(requests=all_requests)


def sane(requests: List[Request]) -> bool:
    if any(not request.completed for request in requests):
        return False

    ordered = sorted(requests)
    return all(a.before(b) for a, b in zip(ordered, ordered[1:]))


@dataclass
class SaneCase:
    id: str
    good: bool
    requests: List[Request]
    marks: Marks = ()


@datacases(
    SaneCase(
        id="all in order",
        good=True,
        requests=[
            Request(id="0", priority=LockPriority.high, acquisition_order=0, release_order=1, completed=True),
            Request(id="1", priority=LockPriority.high, acquisition_order=2, release_order=3, completed=True),
            Request(id="2", priority=LockPriority.high, acquisition_order=4, release_order=5, completed=True),
        ],
    ),
    SaneCase(
        id="incomplete",
        good=False,
        requests=[
            Request(id="0", priority=LockPriority.high, acquisition_order=0, release_order=1, completed=True),
            Request(id="1", priority=LockPriority.high, acquisition_order=2, release_order=3, completed=True),
            Request(id="2", priority=LockPriority.high, acquisition_order=4, release_order=None, completed=False),
        ],
    ),
    SaneCase(
        id="overlapping",
        good=False,
        requests=[
            Request(id="0", priority=LockPriority.high, acquisition_order=0, release_order=2, completed=True),
            Request(id="1", priority=LockPriority.high, acquisition_order=1, release_order=3, completed=True),
            Request(id="2", priority=LockPriority.high, acquisition_order=4, release_order=5, completed=True),
        ],
    ),
    SaneCase(
        id="out of order",
        good=True,
        requests=[
            Request(id="1", priority=LockPriority.high, acquisition_order=2, release_order=3, completed=True),
            Request(id="0", priority=LockPriority.high, acquisition_order=0, release_order=1, completed=True),
            Request(id="2", priority=LockPriority.high, acquisition_order=4, release_order=5, completed=True),
        ],
    ),
)
def test_sane_all_in_order(case: SaneCase) -> None:
    assert sane(requests=case.requests) == case.good


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


@pytest.mark.asyncio
async def test_multiple_tasks_track_active_task_accurately() -> None:
    queue = await LockQueue.create(priority_type=LockPriority)

    other_task_allow_release_event = asyncio.Event()

    async def other_task_function(queued_event: asyncio.Event) -> None:
        async with queue.acquire(priority=LockPriority.high, queued_callback=queued_event.set):
            await other_task_allow_release_event.wait()

    async with queue.acquire(priority=LockPriority.high):
        other_task_queued_event = asyncio.Event()
        other_task = asyncio.create_task(other_task_function(other_task_queued_event))
        await other_task_queued_event.wait()

    async with queue.acquire(priority=LockPriority.high, queued_callback=other_task_allow_release_event.set):
        pass

    await other_task
