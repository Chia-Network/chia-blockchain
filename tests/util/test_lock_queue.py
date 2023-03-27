from __future__ import annotations

import asyncio
import enum
import logging
import time

import pytest

from chia.full_node.lock_queue import LockQueue

log = logging.getLogger(__name__)


class LockPriority(enum.IntEnum):
    # lower values are higher priority
    low = 1
    high = 0


class TestLockQueue:
    @pytest.mark.asyncio
    async def test_lock_queue(self):
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
