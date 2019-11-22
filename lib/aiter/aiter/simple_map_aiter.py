import asyncio
import logging


async def simple_map_aiter(map_f, aiter):
    """
    Take an async iterator and a map function, and apply the function
    to everything coming out of the iterator before passing it on.

    :type aiter: async iterator
    :param aiter: an aiter

    :type map_f: a function, regular or async, that accepts a single parameter
    :param map_f: the mapping function

    :return: an aiter returning transformed items that have been processed through map_f
    :rtype: async iterator
    """
    if asyncio.iscoroutinefunction(map_f):
        _map_f = map_f
    else:
        async def _map_f(_):
            return map_f(_)

    async for _ in aiter:
        try:
            yield await _map_f(_)
        except Exception:
            logging.exception("unhandled mapping function %s worker exception on %s", map_f, _)
