import inspect

from .parallel_map_aiter import parallel_map_aiter
from .simple_map_aiter import simple_map_aiter


def map_aiter(map_f, aiter, worker_count=1):
    """
    Take an async iterator and a map function, and apply the function
    to everything coming out of the iterator before passing it on.
    In this case, the map_f must return a list, which will be flattened.
    Empty lists are okay, so you can filter items by excluding them from the list.

    Note that since there are multiple workers, the order or processed elements
    might not match the input order.

    :type aiter: async iterator
    :param aiter: an aiter

    :type map_f: a function, regular or async, that accepts a single parameter and returns
        a list (or other iterable)
    :param map_f: the mapping function

    :type worker_count: int
    :param worker_count: the number of worker tasks that pull items out of aiter

    :return: an aiter returning transformed items that have been processed through map_f
    :rtype: an async iterator
    """

    if (worker_count > 1 and
            not inspect.iscoroutinefunction(map_f) and
            not inspect.isasyncgenfunction(map_f)):
        raise ValueError(
            "map_f is not a coroutine, which makes "
            "it pointless to use more than 1 worker")

    if worker_count > 1:
        return parallel_map_aiter(map_f, aiter, worker_count)
    return simple_map_aiter(map_f, aiter)
