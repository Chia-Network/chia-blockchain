def partial_async_gen(f, *args):
    """
    Returns an async generator function which is equalivalent to the passed in function,
    but only takes in one parameter (the first one).
    """

    async def inner(first_param):
        async for x in f(first_param, *args):
            yield x

    return inner


def partial_async(f, *args):
    """
    Returns an async function which is equalivalent to the passed in function,
    but only takes in one parameter (the first one).
    """

    async def inner(first_param):
        return await f(first_param, *args)

    return inner
