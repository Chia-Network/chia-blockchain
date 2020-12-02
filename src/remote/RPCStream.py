import asyncio
import weakref

from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Type

from .proxy import Proxy
from .response import Response
from .RPCMessage import RPCMessage


class RPCStream:
    def __init__(
        self,
        msg_aiter_in: AsyncGenerator[RPCMessage, None],
        async_msg_out_callback,
        rpc_message_class: Type[RPCMessage],
        bad_channel_callback=None,
    ):
        """
        msg_aiter_in: yields `RPCMessage`
        async_msg_out_callback: accepts push of `RPCMessage`
        msg_for_invocation: turns the invocation into an (opaque) message
        bad_channel_callback: this is called when a reference an invalid channel occurs. For debugging.
        """
        self._msg_aiter_in = msg_aiter_in
        self._async_msg_out_callback = async_msg_out_callback
        self._rpc_message_class: Type[RPCMessage] = rpc_message_class
        self._bad_channel_callback = bad_channel_callback
        self._next_channel: int = 0
        self._inputs_task: Optional[Awaitable] = None
        self._local_objects_by_channel: Any = weakref.WeakValueDictionary()  # Type  Dict[int, Any]
        self._remote_channels_by_proxy: Any = weakref.WeakKeyDictionary()  # Type : Dict[Proxy, int]

    def next_channel(self) -> int:
        channel = self._next_channel
        self._next_channel += 1
        return channel

    def register_local_obj(self, obj: Any):
        if obj in self._local_objects_by_channel:
            return self._local_objects_by_channel.get(obj)
        channel = self.next_channel()
        self._local_objects_by_channel[channel] = obj
        return channel

    def local_object_for_channel(self, channel: int) -> Optional[Any]:
        return self._local_objects_by_channel.get(channel)

    def remote_obj(self, cls, channel: int) -> Proxy:
        """
        This returns a `Proxy` instance which only allows async method invocations.
        """

        async def callback_f(attr_name, args, kwargs, annotations, is_one_shot):
            future = asyncio.Future()
            return_type = annotations.get("return")
            response = Response(future, return_type)
            source = self.register_local_obj(response)

            to_simple_types = self._rpc_message_class.to_simple_types
            raw_args, raw_kwargs = recast_arguments(annotations, to_simple_types, args, kwargs, self)
            msg = self._rpc_message_class.for_invocation(attr_name, raw_args, raw_kwargs, source, channel)
            await self._async_msg_out_callback(msg)
            if is_one_shot:
                return None

            return await future

        proxy = Proxy(cls, callback_f)
        self._remote_channels_by_proxy[proxy] = channel
        return proxy

    def start(self) -> None:
        """
        Start the task that fetches requests and generates responses.
        It runs until the `msg_aiter_in` stops.
        """
        if self._inputs_task:
            raise RuntimeError(f"{self} already running")
        self._inputs_task = asyncio.create_task(self._run_inputs())

    async def process_msg_for_obj(self, msg: RPCMessage, obj: Any) -> Any:
        """
        This method accepts a message and an object, and handles it.
        There are two cases: the message is a request, or the message is a response.
        """
        # check if request vs response
        method_name = msg.method_name()
        if method_name:
            # it's a request

            source = msg.source()
            try:
                method = getattr(obj, method_name, None)
                if method is None:
                    raise ValueError(f"no method {method} on {obj}")
                annotations = method.__annotations__

                raw_args, raw_kwargs = msg.args_and_kwargs()
                args, kwargs = recast_arguments(annotations, msg.from_simple_types, raw_args, raw_kwargs, self)
                is_one_shot = getattr(method, "one_shot", False)
                r = await method(*args, **kwargs)

                if is_one_shot:
                    return None

                return_type = annotations.get("return")
                simple_r = recast_to_type(r, return_type, msg.to_simple_types, self)

                return self._rpc_message_class.for_response(source, simple_r)
            except Exception as ex:
                return self._rpc_message_class.for_exception(source, ex)

        # it's a response, and obj is a Response
        return_type = obj.return_type
        exception = msg.exception()
        if exception:
            obj.future.set_exception(exception)
        else:
            final_r = recast_to_type(msg.response(), return_type, msg.from_simple_types, self)
            obj.future.set_result(final_r)
        return None

    async def handle_message(self, msg: RPCMessage) -> None:
        target = msg.target()
        obj = self._local_objects_by_channel.get(target)
        if obj is None:
            if self._bad_channel_callback:
                self._bad_channel_callback(target)
                return
        r_msg = await self.process_msg_for_obj(msg, obj)
        if r_msg:
            await self._async_msg_out_callback(r_msg)

    async def _run_inputs(self):
        async for msg in self._msg_aiter_in:
            await self.handle_message(msg)

    async def await_closed(self):
        """
        Wait for `msg_aiter_in` to stop.
        """
        await self._inputs_task


def recast_to_type(
    value: Any,
    the_type: Type,
    cast_simple_type: Callable[[Any, Type, RPCStream], Any],
    rpc_stream: RPCStream,
) -> Any:
    """
    Take the given value `value`, and recast it to type `the_type`, using `cast_simple_type`,
    drilling down through the hierarchy if necessary.
    """

    origin = getattr(the_type, "__origin__", None)

    if origin is dict:
        key_type, value_type = the_type.__args__
        return {
            recast_to_type(k, key_type, cast_simple_type, rpc_stream): recast_to_type(
                v, value_type, cast_simple_type, rpc_stream
            )
            for k, v in value.items()
        }

    if origin is list:
        value_type = the_type.__args__[0]
        return list(recast_to_type(_, value_type, cast_simple_type, rpc_stream) for _ in value)

    return cast_simple_type(value, the_type, rpc_stream)


def recast_arguments(
    annotations: Dict[str, Type],
    cast_simple_type: Callable[[Any, Type, RPCStream], Any],
    args: List[Any],
    kwargs: Dict[str, Any],
    rpc_stream: RPCStream,
) -> Any:
    """
    Returns `args`, `kwargs`, using the annotation hints and cast function.
    """

    cast_args = [recast_to_type(v, t, cast_simple_type, rpc_stream) for v, t in zip(args, annotations.values())]

    cast_kwargs = {}

    for k, t in kwargs.items():
        annotation = annotations.get(k)
        if annotation is None:
            raise ValueError("Annotation is None")
        cast_kwargs[k] = recast_to_type(t, annotation, cast_simple_type, rpc_stream)

    return cast_args, cast_kwargs
