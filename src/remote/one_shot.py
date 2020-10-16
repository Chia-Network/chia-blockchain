def one_shot(method):
    async def new_f(*args, **kwargs):
        await method(*args, **kwargs)
        return None

    new_f.__annotations__ = method.__annotations__
    new_f.one_shot = True
    return new_f
