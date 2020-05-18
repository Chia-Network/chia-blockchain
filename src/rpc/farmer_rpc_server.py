from typing import Callable, List, Set

from aiohttp import web
import logging
import asyncio
import aiohttp
import json
import traceback

from src.farmer import Farmer
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from src.util.byte_types import hexstr_to_bytes
from src.util.json_util import obj_to_response
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.logging import initialize_logging
from src.util.ws_message import create_payload, format_response, pong

log = logging.getLogger(__name__)


class FarmerRpcApiHandler:
    """
    Implementation of farmer RPC API.
    """

    def __init__(self, farmer: Farmer, stop_cb: Callable):
        self.farmer = farmer
        self.stop_cb: Callable = stop_cb
        initialize_logging(
            "RPC Farmer %(name)-25s", self.farmer.config["logging"], DEFAULT_ROOT_PATH,
        )
        self.log = log
        self.shut_down = False
        self.service_name = "chia_farmer"

    async def stop(self):
        self.shut_down = True
        await self.websocket.close()

    async def state_changed(self, change: str):
        if self.websocket is None:
            return

        if change == "challenges":
            data = await self._get_latest_challenges()
            try:
                await self.websocket.send_str(
                    create_payload("get_latest_challenges", data, self.service_name, "wallet_ui")
                )
            except (BaseException) as e:
                try:
                    self.log.warning(f"Sending data failed. Exception {type(e)}.")
                except BrokenPipeError:
                    pass

    async def _get_latest_challenges(self) -> List:
        response = []
        seen_challenges: Set = set()
        for pospace_fin in self.farmer.challenges[self.farmer.current_weight]:
            estimates = self.farmer.challenge_to_estimates.get(
                pospace_fin.challenge_hash, []
            )
            if pospace_fin.challenge_hash in seen_challenges:
                continue
            response.append(
                {
                    "challenge": pospace_fin.challenge_hash,
                    "weight": pospace_fin.weight,
                    "height": pospace_fin.height,
                    "difficulty": pospace_fin.difficulty,
                    "estimates": estimates,
                }
            )
            seen_challenges.add(pospace_fin.challenge_hash)
        return response

    async def get_latest_challenges(self, request) -> web.Response:
        """
        Retrieves the latest challenge, including height, weight, and time to completion estimates.
        """
        return obj_to_response(await self._get_latest_challenges())

    async def _get_connections(self) -> List:
        if self.farmer.server is None:
            return []
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
        return con_info

    async def get_connections(self, request) -> web.Response:
        """
        Retrieves all connections to this farmer.
        """
        return obj_to_response(await self._get_connections())

    async def _open_connection(self, host, port):
        target_node: PeerInfo = PeerInfo(host, uint16(int(port)))

        if self.farmer.server is None or not (
            await self.farmer.server.start_client(target_node, None)
        ):
            raise web.HTTPInternalServerError()

    async def open_connection(self, request) -> web.Response:
        """
        Opens a new connection to another node.
        """
        request_data = await request.json()
        host = request_data["host"]
        port = request_data["port"]
        await self._open_connection(host, port)
        return obj_to_response("")

    async def _close_connection(self, node_id):
        node_id = hexstr_to_bytes(node_id)
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

    async def close_connection(self, request) -> web.Response:
        """
        Closes a connection given by the node id.
        """
        request_data = await request.json()
        await self._close_connection(request_data["node_id"])
        return obj_to_response("")

    async def stop_node(self, request) -> web.Response:
        """
        Shuts down the node.
        """
        if self.stop_cb is not None:
            self.stop_cb()
        return obj_to_response("")

    async def ws_api(self, message):
        """
        This function gets called when new message is received via websocket.
        """

        command = message["command"]
        if message["ack"]:
            return None

        data = None
        if "data" in message:
            data = message["data"]
        if command == "ping":
            return pong()
        elif command == "get_connections":
            return await self._get_connections()
        elif command == "get_latest_challenges":
            return await self._get_latest_challenges()
        elif command == "stop_node":
            await self._stop_node()
            response = {"success": True}
            return response
        elif command == "open_connection":
            assert data is not None
            host = data["host"]
            port = data["port"]
            await self._open_connection(host, port)
            response = {"success": True}
            return response
        elif command == "close_connection":
            assert data is not None
            node_id = data["node_id"]
            await self._close_connection(node_id)
            return response
        else:
            response_2 = {"error": f"unknown_command {command}"}
            return response_2

    async def safe_handle(self, websocket, payload):
        message = None
        try:
            message = json.loads(payload)
            response = await self.ws_api(message)
            if response is not None:
                self.log.info(f"message: {message}")
                self.log.info(f"response: {response}")
                self.log.info(f"payload: {format_response(message, response)}")
                await websocket.send_str(format_response(message, response))

        except BaseException as e:
            tb = traceback.format_exc()
            self.log.error(f"Error while handling message: {tb}")
            error = {"success": False, "error": f"{e}"}
            if message is None:
                return
            await websocket.send_str(format_response(message, error))

    async def connection(self, ws):
        data = {"service": self.service_name}
        payload = create_payload("register_service", data, self.service_name, "daemon")
        await ws.send_str(payload)

        while True:
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                message = msg.data.strip()
                self.log.info(f"received message: {message}")
                await self.safe_handle(ws, message)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                self.log.warning("Received binary data")
            elif msg.type == aiohttp.WSMsgType.PING:
                await ws.pong()
            elif msg.type == aiohttp.WSMsgType.PONG:
                self.log.info("Pong received")
            else:
                if msg.type == aiohttp.WSMsgType.CLOSE:
                    print("Closing")
                    await ws.close()
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print("Error during receive %s" % ws.exception())
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    pass

                break

        await ws.close()

    async def connect_to_daemon(self):
        while True:
            session = None
            try:
                if self.shut_down:
                    break
                session = aiohttp.ClientSession()
                async with session.ws_connect(
                    "ws://127.0.0.1:55400", autoclose=False, autoping=True
                ) as ws:
                    self.websocket = ws
                    await self.connection(ws)
                self.websocket = None
                await session.close()
            except BaseException as e:
                self.log.error(f"Exception: {e}")
                if session is not None:
                    await session.close()
                pass
            await asyncio.sleep(1)


async def start_rpc_server(farmer: Farmer, stop_node_cb: Callable, rpc_port: uint16):
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    handler = FarmerRpcApiHandler(farmer, stop_node_cb)
    app = web.Application()

    farmer._set_state_changed_callback(handler.state_changed)

    app.add_routes(
        [
            web.post("/get_latest_challenges", handler.get_latest_challenges),
            web.post("/get_connections", handler.get_connections),
            web.post("/open_connection", handler.open_connection),
            web.post("/close_connection", handler.close_connection),
            web.post("/stop_node", handler.stop_node),
        ]
    )
    daemon_connection = asyncio.create_task(handler.connect_to_daemon())
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", int(rpc_port))
    await site.start()

    async def cleanup():
        await handler.stop()
        await runner.cleanup()
        await daemon_connection

    return cleanup
