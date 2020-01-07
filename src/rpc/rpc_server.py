import dataclasses
import json

from typing import Any, Callable, List, Optional

from aiohttp import web

from src.full_node import FullNode
from src.types.header_block import HeaderBlock
from src.types.full_block import FullBlock
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from src.util.byte_types import hexstr_to_bytes


"""
Get Blockchain state -> {tips, lca, sync mode}
Get block -> block
Get header -> header
Get connections -> connections
Open connection -> None
Close connection -> None
Stop node -> None
"""


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o: Any):
        if dataclasses.is_dataclass(o):
            return o.to_json()
        elif hasattr(type(o), "__bytes__"):
            return f"0x{bytes(o).hex()}"
        return super().default(o)


def obj_to_response(o: Any) -> web.Response:
    json_str = json.dumps(o, cls=EnhancedJSONEncoder, sort_keys=True)
    return web.Response(body=json_str, content_type="application/json")


class Handler:
    def __init__(self, full_node: FullNode, stop_cb: Callable):
        self.full_node = full_node
        self.stop_cb: Callable = stop_cb

    async def get_blockchain_state(self, request) -> web.Response:
        tips_hb: List[HeaderBlock] = self.full_node.blockchain.get_current_tips()
        lca_hb: HeaderBlock = self.full_node.blockchain.lca_block
        tips = [{"height": hb.height, "header_hash": hb.header_hash} for hb in tips_hb]
        lca = {"height": lca_hb.height, "header_hash": lca_hb.header_hash}
        sync_mode: bool = await self.full_node.store.get_sync_mode()
        response = {"tips": tips, "lca": lca, "sync_mode": sync_mode}
        return obj_to_response(response)

    async def get_block(self, request) -> web.Response:
        request_data = await request.json()
        if "header_hash" not in request_data:
            return web.HTTPBadRequest()
        header_hash = hexstr_to_bytes(request_data["header_hash"])

        block: Optional[FullBlock] = await self.full_node.store.get_block(header_hash)
        if block is None:
            return web.HTTPNotFound()
        return obj_to_response(block)

    async def get_header(self, request) -> web.Response:
        request_data = await request.json()
        if "header_hash" not in request_data:
            return web.HTTPBadRequest()
        header_hash = hexstr_to_bytes(request_data["header_hash"])
        header_block: Optional[
            HeaderBlock
        ] = self.full_node.blockchain.header_blocks.get(header_hash, None)
        if header_block is None:
            return web.HTTPNotFound()
        return obj_to_response(header_block.header)

    async def get_connections(self, request) -> web.Response:
        if self.full_node.server is None:
            return obj_to_response([])
        connections = self.full_node.server.global_connections.get_connections()
        con_info = [
            {
                "type": con.connection_type,
                "local_host": con.local_host,
                "local_port": con.local_port,
                "peer_host": con.peer_host,
                "peer_port:": con.peer_port,
                "peer_server_port": con.peer_server_port,
                "node_id": con.node_id,
                "creation_time": con.creation_time,
                "bytes_read": con.bytes_read,
                "bytes_written": con.bytes_written,
                "last_message_time": con.last_message_time,
            }
            for con in connections
        ]
        return obj_to_response(con_info)

    async def open_connection(self, request) -> web.Response:
        request_data = await request.json()
        host = request_data["host"]
        port = request_data["port"]
        target_node: PeerInfo = PeerInfo(host, uint16(int(port)))

        if self.full_node.server is None or not (
            await self.full_node.server.start_client(target_node, None)
        ):
            return web.HTTPInternalServerError()
        return web.Response(text="")

    async def close_connection(self, request) -> web.Response:
        request_data = await request.json()
        node_id = hexstr_to_bytes(request_data["node_id"])
        if self.full_node.server is None:
            return web.HTTPInternalServerError()

        connections_to_close = [
            c
            for c in self.full_node.server.global_connections.get_connections()
            if c.node_id == node_id
        ]
        if len(connections_to_close) == 0:
            return web.HTTPNotFound()
        for connection in connections_to_close:
            self.full_node.server.global_connections.close(connection)
        return obj_to_response({})

    async def stop_node(self, request) -> web.Response:
        if self.stop_cb is not None:
            self.stop_cb()
        return obj_to_response({})


async def start_server(full_node: FullNode, stop_node_cb: Callable, rpc_port: int):
    handler = Handler(full_node, stop_node_cb)
    app = web.Application()
    app.add_routes(
        [
            web.post("/get_blockchain_state", handler.get_blockchain_state),
            web.post("/get_block", handler.get_block),
            web.post("/get_header", handler.get_header),
            web.post("/get_connections", handler.get_connections),
            web.post("/open_connection", handler.open_connection),
            web.post("/close_connection", handler.close_connection),
            web.post("/stop_node", handler.stop_node),
        ]
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", rpc_port)
    await site.start()

    async def cleanup():
        await runner.cleanup()

    return cleanup
