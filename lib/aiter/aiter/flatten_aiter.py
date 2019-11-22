async def flatten_aiter(aiter):
    """
    Take an async iterator that returns lists and return the individual
    elements.

    :type aiter: aiter
    :param aiter: an async iterator yielding lists

    :return: an async iterator where the elements are the flattened inputs
    :rtype: an async iterator
    """
    async for items in aiter:
        try:
            for _ in items:
                yield _
        except Exception:
            pass
