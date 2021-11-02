import asyncio
import logging
import time
from asyncio import CancelledError

import pytest

from chia.full_node.lock_queue import LockQueue, LockClient, TooManyLockClients

log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestLockQueue:
    @pytest.mark.asyncio
    async def test_lock_queue(self):
        lock = asyncio.Lock()

        queue = LockQueue(lock)

        low_priority_client = LockClient(1, queue)
        high_priority_client = LockClient(0, queue)

        async def very_slow_func():
            await asyncio.sleep(2)
            raise CancelledError()


        async def slow_func():
            for i in range(100):
                await asyncio.sleep(0.01)

        async def kind_of_slow_func():
            for i in range(100):
                await asyncio.sleep(0.001)

        async def do_high():
            nonlocal high_priority_client
            for i in range(10):
                log.warning("Starting high")
                t1 = time.time()
                async with high_priority_client:
                    log.warning(f"Spend {time.time() - t1} waiting for high")
                    await slow_func()

        async def do_low(i: int):
            nonlocal low_priority_client
            log.warning(f"Starting low {i}")
            t1 = time.time()
            async with low_priority_client:
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

        # Test limit
        another_client = LockClient(1, queue, 10)

        async def do_another(i: int):
            nonlocal another_client
            async with another_client:
                await kind_of_slow_func()

        tasks = [asyncio.create_task(do_another(i)) for i in range(20)]

        failed = False
        for task in tasks:
            try:
                await task
            except TooManyLockClients:
                failed = True
        assert failed

        assert low_priority_client._curr_clients == 0
        assert high_priority_client._curr_clients == 0

        with pytest.raises(CancelledError):
            async with high_priority_client:
                await very_slow_func()

        assert high_priority_client._curr_clients == 0
        queue.close()
