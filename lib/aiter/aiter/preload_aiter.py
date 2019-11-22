from .gated_aiter import gated_aiter


async def preload_aiter(preload_size, aiter):
    """
    This aiter wraps around another aiter, and forces a preloaded
    buffer of the given size. When an element is removed, the loader is
    given a kick to try to refill the preload buffer.

    :type preload_size: int
    :param preload_size: the maximum number of items to attempt to preload

    :type aiter: async iterator
    :param aiter: an aiter

    :return: an async iterator yielding the same values as the original aiter
    :rtype: async iterator
    """

    gate = gated_aiter(aiter)
    gate.push(preload_size)
    async for _ in gate:
        yield _
        gate.push(1)
    gate.stop()
