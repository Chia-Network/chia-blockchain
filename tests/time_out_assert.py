import asyncio
import time
import logging
from typing import Callable

from src.protocols.protocol_message_types import ProtocolMessageTypes

log = logging.getLogger(__name__)


async def time_out_assert_custom_interval(timeout: int, interval, function, value=True, *args, **kwargs):
    start = time.time()
    while time.time() - start < timeout:
        if asyncio.iscoroutinefunction(function):
            f_res = await function(*args, **kwargs)
        else:
            f_res = function(*args, **kwargs)
        if value == f_res:
            return
        await asyncio.sleep(interval)
    assert False


async def time_out_assert(timeout: int, function, value=True, *args, **kwargs):
    await time_out_assert_custom_interval(timeout, 0.05, function, value, *args, *kwargs)


async def time_out_assert_not_none(timeout: int, function, *args, **kwargs):
    start = time.time()
    while time.time() - start < timeout:
        if asyncio.iscoroutinefunction(function):
            f_res = await function(*args, **kwargs)
        else:
            f_res = function(*args, **kwargs)
        if f_res is not None:
            return
        await asyncio.sleep(0.05)
    assert False


def time_out_messages(incoming_queue: asyncio.Queue, msg_name: str, count: int = 1) -> Callable:
    async def bool_f():
        if incoming_queue.qsize() < count:
            return False
        for _ in range(count):
            response = (await incoming_queue.get())[0].type
            if ProtocolMessageTypes(response).name != msg_name:
                # log.warning(f"time_out_message: found {response} instead of {msg_name}")
                return False
        return True

    return bool_f
