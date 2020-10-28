from src.server.outbound_message import Message


class Proxy(object):
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

    def __init__(self, cls, callback_f, local_cls):
        self.cls = cls
        self.callback_f = callback_f
        self.local_cls = local_cls

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

            msg = Message(attr_name, args)
            result = await self.callback_f(msg)
            if result is not None:
                ret_attr = getattr(self.local_cls, result.function, None)
                req_annotation = ret_attr.__annotations__
                req = req_annotation["request"]
                result = req(**result.data)
            return result

        return invoke

    def __repr__(self):
        return f"<Proxy for {self.cls} at {hex(id(self))}>"
