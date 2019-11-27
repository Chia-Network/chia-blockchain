from typing import Callable, List, Dict, get_type_hints, Any
from aiohttp import web
from src.database import FullNodeStore
from src.server.server import ChiaServer
from src.blockchain import Blockchain
from src.util.ints import uint16
from src.protocols import local_api
from src.types.peer_info import PeerInfo
import json
import dataclasses


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            fields: Dict = get_type_hints(o)
            return {f_name: getattr(o, f_name) for f_name in fields.keys()}
        elif isinstance(o, bytes):
            return "0x" + o.hex()
        elif hasattr(type(o), "__bytes__"):
            return bytes(o)
        return super().default(o)


class FullNodeLocalApi:
    def __init__(self, blockchain: Blockchain, store: FullNodeStore, server: ChiaServer,
                 close_cb: Callable, port: uint16):
        self.blockchain = blockchain
        self.store = store
        self.server = server
        self.port = port
        self.close_cb = close_cb

    async def start(self):
        app = web.Application()
        app.add_routes([
            web.get('/', self.root),
            web.post('/stop_node', self.stop_node),
            web.get('/get_connections', self.get_connections),
            web.post('/add_connections', self.add_connection),
            ])
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, 'localhost', int(self.port))
        await site.start()

    async def close(self):
        await self.runner.cleanup()

    async def stop_node(self, request):
        self.close_cb()
        return web.Response()

    def encode_response(self, response: Any):
        return

    async def get_connections(self, request):
        responses: List[local_api.Connection] = []
        for connection in self.server.global_connections.get_connections():
            if connection.peer_port is not None:
                peer_info = PeerInfo(connection.peer_host, connection.peer_port)
                assert connection.connection_type is not None
                assert connection.node_id is not None
                responses.append(local_api.Connection(peer_info, connection.connection_type,
                                                      connection.node_id))

        response = local_api.GetConnectionsResponse(responses)
        return web.Response(text=str(json.dumps(response, cls=EnhancedJSONEncoder)))

    async def add_connection(self, request):
        pass

    async def root(self, request):
        text = "This is the Chia local API server"
        return web.Response(text=text)
