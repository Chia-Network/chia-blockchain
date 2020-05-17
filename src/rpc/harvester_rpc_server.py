from typing import Callable, List

from aiohttp import web
import logging
import asyncio
import aiohttp
import json
import traceback

from src.harvester import Harvester
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from src.util.byte_types import hexstr_to_bytes
from src.util.json_util import obj_to_response
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.logging import initialize_logging
from src.util.ws_message import create_payload, format_response, pong

log = logging.getLogger(__name__)


class HarvesterRpcApiHandler:
    """
    Implementation of harvester RPC API.
    """

    def __init__(self, harvester: Harvester, stop_cb: Callable):
        self.harvester = harvester
        self.stop_cb: Callable = stop_cb
        initialize_logging(
            "RPC Harvester %(name)-25s",
            self.harvester.config["logging"],
            DEFAULT_ROOT_PATH,
        )
        self.log = log
        self.shut_down = False
        self.service_name = "chia_harvester"

    async def stop(self):
        self.shut_down = True
        await self.websocket.close()

    async def _get_plots(self) -> List:
        return self.harvester._get_plots()

    async def get_plots(self, request) -> web.Response:
        """
        Retrieves the latest challenge, including height, weight, and time to completion estimates.
        """
        response = await self._get_plots()
        return obj_to_response(response)

    async def _refresh_plots(self):
        self.harvester._refresh_plots()

    async def refresh_plots(self, request) -> web.Response:
        await self._refresh_plots()
        return obj_to_response({})

    async def _delete_plot(self, filename) -> bool:
        return self.harvester._delete_plot(filename)

    async def delete_plot(self, request) -> web.Response:
        request_data = await request.json()
        filename = request_data["filename"]
        response = await self._delete_plot(filename)
        return obj_to_response(response)

    async def _get_connections(self) -> List:
        if self.harvester.server is None:
            return []
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
        return con_info

    async def get_connections(self, request) -> web.Response:
        """
        Retrieves all connections to this harvester.
        """
        return obj_to_response(await self._get_connections())

    async def _open_connection(self, host, port):
        target_node: PeerInfo = PeerInfo(host, uint16(int(port)))

        if self.harvester.server is None or not (
            await self.harvester.server.start_client(target_node, None)
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
        elif command == "get_plots":
            return await self._get_plots()
        elif command == "refresh_plots":
            await self._refresh_plots()
            response = {"success": True}
            return response
        elif command == "delete_plot":
            assert data is not None
            filename = data["filename"]
            return await self._delete_plot(filename)
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


async def start_rpc_server(
    harvester: Harvester, stop_node_cb: Callable, rpc_port: uint16
):
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    handler = HarvesterRpcApiHandler(harvester, stop_node_cb)
    app = web.Application()

    app.add_routes(
        [
            web.post("/get_plots", handler.get_plots),
            web.post("/refresh_plots", handler.refresh_plots),
            web.post("/delete_plot", handler.delete_plot),
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
