import asyncio
import logging


async def map_filter_aiter(map_f, aiter):
    """
    Take an async iterator and a map function, and apply the function
    to everything coming out of the iterator before passing it on.
    In this case, the map_f must return a list, which will be flattened.
    Empty lists are okay, so you can filter items by excluding them from the list.

    :type aiter: async iterator
    :param aiter: an aiter

    :type map_f: a function, regular or async, that accepts a single parameter and returns
        a list (or other iterable)
    :param map_f: the mapping function

    :return: an aiter returning transformed items that have been processed through map_f
    :rtype: an async iterator
    """
    if asyncio.iscoroutinefunction(map_f):
        _map_f = map_f
    else:
        async def _map_f(_):
            return map_f(_)

    async for _ in aiter:
        try:
            items = await _map_f(_)
            for _ in items:
                yield _
        except Exception:
            logging.exception("unhandled mapping function %s worker exception on %s", map_f, _)
