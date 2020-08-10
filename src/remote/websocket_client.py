import websockets

from .json_packaging import rpc_stream_for_websocket


class WebsocketRemote:
    def __init__(self, uri):
        self._uri = uri

    async def start(self):
        self._websocket = await websockets.connect(self._uri)

    async def __aiter__(self):
        while True:
            _ = await self._websocket.recv()
            yield _

    async def push(self, msg):
        await self._websocket.send(msg)


async def connect_to_remote_api(url, api):
    """
    The given API will be attached to target `0`. The remote better
    have an object that looks like the given api also attached to `0`
    or you'll surely suffer.
    """
    ws = WebsocketRemote(url)
    await ws.start()
    rpc_stream = rpc_stream_for_websocket(ws)
    remote_api = rpc_stream.remote_obj(api, 0)
    rpc_stream.start()

    return remote_api
