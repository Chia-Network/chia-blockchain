import asyncio
import time


async def time_out_assert_custom_interval(
    timeout: int, interval, function, value, *args, **kwargs
):
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


async def time_out_assert(timeout: int, function, value, *args, **kwargs):
    await time_out_assert_custom_interval(
        timeout, 0.05, function, value, *args, *kwargs
    )


async def time_out_assert_not_None(timeout: int, function, *args, **kwargs):
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
