from typing import Callable

from aiohttp import web

from src.farmer import Farmer
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from src.util.byte_types import hexstr_to_bytes
from src.util.network import obj_to_response


class FarmerRpcApiHandler:
    """
    Implementation of farmer RPC API.
    """

    def __init__(self, farmer: Farmer, stop_cb: Callable):
        self.farmer = farmer
        self.stop_cb: Callable = stop_cb

    async def get_latest_challenges(self, request) -> web.Response:
        """
        Retrieves the latest challenge, including height, weight, and time to completion estimates.
        """
        response = []
        for pospace_fin in self.farmer.challenges[self.farmer.current_weight]:
            estimates = self.farmer.challenge_to_estimates.get(pospace_fin.challenge_hash, [])
            response.append(
                {
                    "challenge": pospace_fin.challenge_hash,
                    "weight": pospace_fin.weight,
                    "height": pospace_fin.height,
                    "difficulty": pospace_fin.difficulty,
                    "estimates": estimates,
                }
            )

        return obj_to_response(response)

    async def get_connections(self, request) -> web.Response:
        """
        Retrieves all connections to this farmer.
        """
        if self.farmer.server is None:
            return obj_to_response([])
        connections = self.farmer.server.global_connections.get_connections()
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

        if self.farmer.server is None or not (
            await self.farmer.server.start_client(target_node, None)
        ):
            raise web.HTTPInternalServerError()
        return obj_to_response("")

    async def close_connection(self, request) -> web.Response:
        """
        Closes a connection given by the node id.
        """
        request_data = await request.json()
        node_id = hexstr_to_bytes(request_data["node_id"])
        if self.farmer.server is None:
            raise web.HTTPInternalServerError()

        connections_to_close = [
            c
            for c in self.farmer.server.global_connections.get_connections()
            if c.node_id == node_id
        ]
        if len(connections_to_close) == 0:
            raise web.HTTPNotFound()
        for connection in connections_to_close:
            self.farmer.server.global_connections.close(connection)
        return obj_to_response("")

    async def stop_node(self, request) -> web.Response:
        """
        Shuts down the node.
        """
        if self.stop_cb is not None:
            self.stop_cb()
        return obj_to_response("")


async def start_rpc_server(farmer: Farmer, stop_node_cb: Callable, rpc_port: uint16):
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    handler = FarmerRpcApiHandler(farmer, stop_node_cb)
    app = web.Application()

    app.add_routes(
        [
            web.post("/get_latest_challenges", handler.get_latest_challenges),
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
