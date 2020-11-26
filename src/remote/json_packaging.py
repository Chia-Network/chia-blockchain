"""
This serves as an example for how to stream messages using JSON.

If you replace this, you can change how messages are marshaled.

Requests:
{
    s: source_object,  # an integer
    t: target_object,  # an integer, default 0 object used if missing
    m: method_name,
    a: args,  # *args arguments, or [] if missing
    k: kwargs,  # **kwargs arguments, or {} if missing
}

Responses:
{
    t: target_object,  # use the source of the request
    r: return_value,
    e: text of remote exception (or missing if there is an r value)
}
"""

from aiter import map_aiter


from .JSONMessage import JSONMessage
from .RPCStream import RPCStream


def make_push_callback(push):
    """
    This is just an async wrapper around a synchronous function.
    """

    async def push_callback(msg):
        await push(msg.serialize_text())

    return push_callback


def rpc_stream(ws, msg_aiter_in, async_msg_out_callback):
    return RPCStream(
        msg_aiter_in,
        async_msg_out_callback,
        JSONMessage,
    )


"""
There are two main websocket libraries: `websockets` and `aiohttp`, and each
creates slightly different natural aiter streams, so these two functions
make them look the same.
"""


def rpc_stream_for_websocket(ws):
    msg_aiter_in = map_aiter(JSONMessage.deserialize_text, ws)
    async_msg_out_callback = make_push_callback(ws.push)
    return rpc_stream(ws, msg_aiter_in, async_msg_out_callback)


def rpc_stream_for_websocket_aiohttp(ws):
    aiter_1 = map_aiter(lambda _: _.data, ws)
    msg_aiter_in = map_aiter(JSONMessage.deserialize_text, aiter_1)
    async_msg_out_callback = make_push_callback(ws.send_str)
    return rpc_stream(ws, msg_aiter_in, async_msg_out_callback)
