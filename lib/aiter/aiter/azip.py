async def azip(*aiters):
    """
    async version of zip
    This function takes a list of async iterators and returns a single async iterator
    that yields tuples of elements.

    This iterator advances as slow its slowest component (obviously).

    example:
        async for a, b, c in azip(aiter1, aiter2, aiter3):
            print(a, b, c)

    :type aiters: aiters
    :param aiters: one or more async iterators

    :return: an aiter returning N-tuples similar to zip
    :rtype: an aiter
    """
    anext_tuple = tuple([_.__aiter__() for _ in aiters])
    while True:
        try:
            next_tuple = tuple([await _.__anext__() for _ in anext_tuple])
        except StopAsyncIteration:
            break
        yield next_tuple
