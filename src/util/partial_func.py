def partial_async_gen(f, first_param):
    """
    Returns an async generator function which is equalivalent to the passed in function,
    but only takes 1 argument instead of two.
    """
    async def inner(second_param):
        async for x in f(first_param, second_param):
            yield x
    return inner


def partial_async(f, first_param):
    """
    Returns an async function which is equalivalent to the passed in function,
    but only takes 1 argument instead of two.
    """
    async def inner(second_param):
        return await f(first_param, second_param)
    return inner
