async def iter_to_aiter(iter):
    """
    :type iter: synchronous iterator
    :param iter: a synchronous iterator

    This converts a regular iterator to an async iterator.
    """
    for _ in iter:
        yield _
