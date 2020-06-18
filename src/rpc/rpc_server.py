from typing import Callable, Dict, Any, List

import aiohttp
import logging
import asyncio
import json
import traceback

from src.types.peer_info import PeerInfo
from src.util.byte_types import hexstr_to_bytes
from src.util.json_util import obj_to_response
from src.util.ws_message import create_payload, format_response, pong
from src.util.ints import uint16

log = logging.getLogger(__name__)


class RpcServer:
    """
    Implementation of RPC server.
    """

    def __init__(self, rpc_api: Any, service_name: str, stop_cb: Callable):
        self.rpc_api = rpc_api
        self.stop_cb: Callable = stop_cb
        self.log = log
        self.shut_down = False
        self.websocket = None
        self.service_name = service_name

    async def stop(self):
        self.shut_down = True
        if self.websocket is not None:
            await self.websocket.close()

    async def _state_changed(self, *args):
        change = args[0]
        assert self.websocket is not None
        payloads: List[str] = await self.rpc_api._state_changed(*args)

        if change == "add_connection" or change == "close_connection":
            data = await self.get_connections({})
            payload = create_payload(
                "get_connections", data, self.service_name, "wallet_ui"
            )
            payloads.append(payload)
        for payload in payloads:
            try:
                await self.websocket.send_str(payload)
            except Exception as e:
                self.log.warning(f"Sending data failed. Exception {type(e)}.")

    def state_changed(self, *args):

        if self.websocket is None:
            return
        asyncio.create_task(self._state_changed(*args))

    def _wrap_http_handler(self, f) -> Callable:
        async def inner(request) -> aiohttp.web.Response:
            request_data = await request.json()
            res_object = await f(request_data)
            if res_object is None:
                raise aiohttp.web.HTTPNotFound()
            return obj_to_response(res_object)

        return inner

    async def get_connections(self, request: Dict) -> Dict:
        if self.rpc_api.service.global_connections is None:
            return {"success": False}
        connections = self.rpc_api.service.global_connections.get_connections()
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
        return {"success": True, "connections": con_info}

    async def open_connection(self, request: Dict):
        host = request["host"]
        port = request["port"]
        target_node: PeerInfo = PeerInfo(host, uint16(int(port)))

        if getattr(self.rpc_api.service, "server", None) is None or not (
            await self.rpc_api.service.server.start_client(target_node, None)
        ):
            raise aiohttp.web.HTTPInternalServerError()
        return {"success": True}

    async def close_connection(self, request: Dict):
        node_id = hexstr_to_bytes(request["node_id"])
        if self.rpc_api.service.global_connections is None:
            raise aiohttp.web.HTTPInternalServerError()
        connections_to_close = [
            c
            for c in self.rpc_api.service.global_connections.get_connections()
            if c.node_id == node_id
        ]
        if len(connections_to_close) == 0:
            raise aiohttp.web.HTTPNotFound()
        for connection in connections_to_close:
            self.rpc_api.service.global_connections.close(connection)
        return {"success": True}

    async def stop_node(self, request):
        """
        Shuts down the node.
        """
        if self.stop_cb is not None:
            self.stop_cb()
        return {"success": True}

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

        f = getattr(self, command, None)
        if f is not None:
            return await f(data)
        f = getattr(self.rpc_api, command, None)
        if f is not None:
            return await f(data)
        else:
            return {"error": f"unknown_command {command}"}

    async def safe_handle(self, websocket, payload):
        message = None
        try:
            message = json.loads(payload)
            response = await self.ws_api(message)
            if response is not None:
                # log.info(f"Sending {message} {response}")
                await websocket.send_str(format_response(message, response))

        except Exception as e:
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
            except Exception as e:
                self.log.warning(f"Exception: {e}")
                if session is not None:
                    await session.close()
            await asyncio.sleep(1)


async def start_rpc_server(
    rpc_api: Any, rpc_port: uint16, stop_cb: Callable, connect_to_daemon=True
):
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    app = aiohttp.web.Application()
    rpc_server = RpcServer(rpc_api, rpc_api.service_name, stop_cb)
    rpc_server.rpc_api.service._set_state_changed_callback(rpc_server.state_changed)
    http_routes: Dict[str, Callable] = rpc_api.get_routes()

    routes = [
        aiohttp.web.post(route, rpc_server._wrap_http_handler(func))
        for (route, func) in http_routes.items()
    ]
    routes += [
        aiohttp.web.post(
            "/get_connections",
            rpc_server._wrap_http_handler(rpc_server.get_connections),
        ),
        aiohttp.web.post(
            "/open_connection",
            rpc_server._wrap_http_handler(rpc_server.open_connection),
        ),
        aiohttp.web.post(
            "/close_connection",
            rpc_server._wrap_http_handler(rpc_server.close_connection),
        ),
        aiohttp.web.post(
            "/stop_node", rpc_server._wrap_http_handler(rpc_server.stop_node)
        ),
    ]

    app.add_routes(routes)
    if connect_to_daemon:
        daemon_connection = asyncio.create_task(rpc_server.connect_to_daemon())
    runner = aiohttp.web.AppRunner(app, access_log=None)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "localhost", int(rpc_port))
    await site.start()

    async def cleanup():
        await rpc_server.stop()
        await runner.cleanup()
        if connect_to_daemon:
            await daemon_connection

    return cleanup
