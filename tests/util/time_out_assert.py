from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.util.timing import adjusted_timeout

log = logging.getLogger(__name__)


async def time_out_assert_custom_interval(timeout: float, interval, function, value=True, *args, **kwargs):
    __tracebackhide__ = True

    timeout = adjusted_timeout(timeout=timeout)

    start = time.time()
    while time.time() - start < timeout:
        if asyncio.iscoroutinefunction(function):
            f_res = await function(*args, **kwargs)
        else:
            f_res = function(*args, **kwargs)
        if value == f_res:
            return None
        await asyncio.sleep(interval)
    assert False, f"Timed assertion timed out after {timeout} seconds: expected {value!r}, got {f_res!r}"


async def time_out_assert(timeout: int, function, value=True, *args, **kwargs):
    __tracebackhide__ = True
    await time_out_assert_custom_interval(timeout, 0.05, function, value, *args, **kwargs)


async def time_out_assert_not_none(timeout: float, function, *args, **kwargs):
    __tracebackhide__ = True

    timeout = adjusted_timeout(timeout=timeout)

    start = time.time()
    while time.time() - start < timeout:
        if asyncio.iscoroutinefunction(function):
            f_res = await function(*args, **kwargs)
        else:
            f_res = function(*args, **kwargs)
        if f_res is not None:
            return None
        await asyncio.sleep(0.05)
    assert False, "Timed assertion timed out"


def time_out_messages(incoming_queue: asyncio.Queue, msg_name: str, count: int = 1) -> Callable:
    async def bool_f():
        if incoming_queue.qsize() < count:
            return False
        for _ in range(count):
            response = (await incoming_queue.get()).type
            if ProtocolMessageTypes(response).name != msg_name:
                # log.warning(f"time_out_message: found {response} instead of {msg_name}")
                return False
        return True

    return bool_f
