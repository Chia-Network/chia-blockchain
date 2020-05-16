from typing import Callable

from aiohttp import web
from blspy import PrivateKey, PublicKey
from pathlib import Path

from src.harvester import Harvester
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from src.util.byte_types import hexstr_to_bytes
from src.util.network import obj_to_response


class HarvesterRpcApiHandler:
    """
    Implementation of harvester RPC API.
    """

    def __init__(self, harvester: Harvester, stop_cb: Callable):
        self.harvester = harvester
        self.stop_cb: Callable = stop_cb

    async def get_plots(self, request) -> web.Response:
        """
        Retrieves the latest challenge, including height, weight, and time to completion estimates.
        """
        response = self.harvester._get_plots()
        return obj_to_response(response)

    async def refresh_plots(self, request) -> web.Response:
        self.harvester._refresh_plots()
        return obj_to_response({})

    async def delete_plot(self, request) -> web.Response:
        print(request)
        request_data = await request.json()
        absolute_filename = request_data["filename"]
        filename_path = Path(absolute_filename)
        response = self.harvester._delete_plot(filename_path)
        return obj_to_response(response)


    async def get_connections(self, request) -> web.Response:
        """
        Retrieves all connections to this harvester.
        """
        if self.harvester.server is None:
            return obj_to_response([])
        connections = self.harvester.server.global_connections.get_connections()
        con_info = [
            {
                "type": con.connection_type,
                "local_host": con.local_host,
                "local_port": con.local_port,
                "peer_host": con.peer_host,
                "peer_port": con.peer_port,
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
        """
        Opens a new connection to another node.
        """
        request_data = await request.json()
        host = request_data["host"]
        port = request_data["port"]
        target_node: PeerInfo = PeerInfo(host, uint16(int(port)))

        if self.harvester.server is None or not (
            await self.harvester.server.start_client(target_node, None)
        ):
            raise web.HTTPInternalServerError()
        return obj_to_response("")

    async def close_connection(self, request) -> web.Response:
        """
        Closes a connection given by the node id.
        """
        request_data = await request.json()
        node_id = hexstr_to_bytes(request_data["node_id"])
        if self.harvester.server is None:
            raise web.HTTPInternalServerError()

        connections_to_close = [
            c
            for c in self.harvester.server.global_connections.get_connections()
            if c.node_id == node_id
        ]
        if len(connections_to_close) == 0:
            raise web.HTTPNotFound()
        for connection in connections_to_close:
            self.harvester.server.global_connections.close(connection)
        return obj_to_response("")

    async def stop_node(self, request) -> web.Response:
        """
        Shuts down the node.
        """
        if self.stop_cb is not None:
            self.stop_cb()
        return obj_to_response("")


async def start_rpc_server(harvester: Harvester, stop_node_cb: Callable, rpc_port: uint16):
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    handler = HarvesterRpcApiHandler(harvester, stop_node_cb)
    app = web.Application()

    app.add_routes(
        [
            web.post("/get_plots", handler.get_plots),
            web.post("/refresh_plots", handler.delete_plot),
            web.post("/delete_plot", handler.delete_plot),
            web.post("/get_connections", handler.get_connections),
            web.post("/open_connection", handler.open_connection),
            web.post("/close_connection", handler.close_connection),
            web.post("/stop_node", handler.stop_node),
        ]
    )

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", int(rpc_port))
    await site.start()

    async def cleanup():
        await runner.cleanup()

    return cleanup
