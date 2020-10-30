class Proxy:
    """
    This class is a "proxy" object that turns all its attributes
    into callables that simply invoke "callback_f" with the name
    of the attribute and the given context.

    This is so you can create a proxy, then do something like

    proxy.call_my_function(foo, bar)

    and it will actually call

    callback_f("call_my_function", context, foo, bar)

    so the callback_f can actually start a remote procedure call.
    """

    def __init__(self, cls, callback_f):
        self.cls = cls
        self.callback_f = callback_f

    def __getattr__(self, attr_name: str):
        """
        Call the callback_f with `attr_name`, `args`, `kwargs`, `annotations`.
        """

        async def invoke(*args, **kwargs):
            # look in the class for the attribute
            # make sure it's an async function
            # collect up the metadata with types to build args, kwargs with `Argument`
            attribute = getattr(self.cls, attr_name, None)
            if attribute is None:
                raise AttributeError(f"bad attribute {attr_name}")
            is_one_shot = getattr(attribute, "one_shot", False)
            annotations = attribute.__annotations__
            return await self.callback_f(
                attr_name, args, kwargs, annotations, is_one_shot
            )

        return invoke

    def __repr__(self):
        return f"<Proxy for {self.cls} at {hex(id(self))}>"
