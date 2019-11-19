from .iter_to_aiter import iter_to_aiter
from .join_aiters import join_aiters
from .sharable_aiter import sharable_aiter
from .simple_map_aiter import simple_map_aiter


def parallel_map_aiter(map_f, aiter, worker_count):
    """
    Take an async iterator and a map function, and apply the function
    to everything coming out of the iterator before passing it on.

    Note that if there are multiple workers, the order or processed elements
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
    shared_aiter = sharable_aiter(aiter)
    aiters = [simple_map_aiter(
        map_f, shared_aiter) for _ in range(worker_count)]
    return join_aiters(iter_to_aiter(aiters))
