import asyncio
import json
import logging
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import aiohttp

from chia.server.outbound_message import NodeType
from chia.server.server import ssl_context_for_server
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16
from chia.util.json_util import dict_to_json_str, obj_to_response
from chia.util.ws_message import create_payload, create_payload_dict, format_response, pong

log = logging.getLogger(__name__)


class RpcServer:
    """
    Implementation of RPC server.
    """

    def __init__(self, rpc_api: Any, service_name: str, stop_cb: Callable, root_path, net_config):
        self.rpc_api = rpc_api
        self.stop_cb: Callable = stop_cb
        self.log = log
        self.shut_down = False
        self.websocket: Optional[aiohttp.ClientWebSocketResponse] = None
        self.service_name = service_name
        self.root_path = root_path
        self.net_config = net_config
        self.crt_path = root_path / net_config["daemon_ssl"]["private_crt"]
        self.key_path = root_path / net_config["daemon_ssl"]["private_key"]
        self.ca_cert_path = root_path / net_config["private_ssl_ca"]["crt"]
        self.ca_key_path = root_path / net_config["private_ssl_ca"]["key"]
        self.ssl_context = ssl_context_for_server(self.ca_cert_path, self.ca_key_path, self.crt_path, self.key_path)

    async def stop(self):
        self.shut_down = True
        if self.websocket is not None:
            await self.websocket.close()

    async def _state_changed(self, *args):
        if self.websocket is None:
            return None
        payloads: List[Dict] = await self.rpc_api._state_changed(*args)

        change = args[0]
        if change == "add_connection" or change == "close_connection":
            data = await self.get_connections({})
            if data is not None:

                payload = create_payload_dict(
                    "get_connections",
                    data,
                    self.service_name,
                    "wallet_ui",
                )
                payloads.append(payload)
        for payload in payloads:
            if "success" not in payload["data"]:
                payload["data"]["success"] = True
            try:
                await self.websocket.send_str(dict_to_json_str(payload))
            except Exception:
                tb = traceback.format_exc()
                self.log.warning(f"Sending data failed. Exception {tb}.")

    def state_changed(self, *args):
        if self.websocket is None:
            return None
        asyncio.create_task(self._state_changed(*args))

    def _wrap_http_handler(self, f) -> Callable:
        async def inner(request) -> aiohttp.web.Response:
            request_data = await request.json()
            try:
                res_object = await f(request_data)
                if res_object is None:
                    res_object = {}
                if "success" not in res_object:
                    res_object["success"] = True
            except Exception as e:
                tb = traceback.format_exc()
                self.log.warning(f"Error while handling message: {tb}")
                if len(e.args) > 0:
                    res_object = {"success": False, "error": f"{e.args[0]}"}
                else:
                    res_object = {"success": False, "error": f"{e}"}

            return obj_to_response(res_object)

        return inner

    async def get_connections(self, request: Dict) -> Dict:
        if self.rpc_api.service.server is None:
            raise ValueError("Global connections is not set")
        if self.rpc_api.service.server._local_type is NodeType.FULL_NODE:
            # TODO add peaks for peers
            connections = self.rpc_api.service.server.get_connections()
            con_info = []
            if self.rpc_api.service.sync_store is not None:
                peak_store = self.rpc_api.service.sync_store.peer_to_peak
            else:
                peak_store = None
            for con in connections:
                if peak_store is not None and con.peer_node_id in peak_store:
                    peak_hash, peak_height, peak_weight = peak_store[con.peer_node_id]
                else:
                    peak_height = None
                    peak_hash = None
                    peak_weight = None
                con_dict = {
                    "type": con.connection_type,
                    "local_port": con.local_port,
                    "peer_host": con.peer_host,
                    "peer_port": con.peer_port,
                    "peer_server_port": con.peer_server_port,
                    "node_id": con.peer_node_id,
                    "creation_time": con.creation_time,
                    "bytes_read": con.bytes_read,
                    "bytes_written": con.bytes_written,
                    "last_message_time": con.last_message_time,
                    "peak_height": peak_height,
                    "peak_weight": peak_weight,
                    "peak_hash": peak_hash,
                }
                con_info.append(con_dict)
        else:
            connections = self.rpc_api.service.server.get_connections()
            con_info = [
                {
                    "type": con.connection_type,
                    "local_port": con.local_port,
                    "peer_host": con.peer_host,
                    "peer_port": con.peer_port,
                    "peer_server_port": con.peer_server_port,
                    "node_id": con.peer_node_id,
                    "creation_time": con.creation_time,
                    "bytes_read": con.bytes_read,
                    "bytes_written": con.bytes_written,
                    "last_message_time": con.last_message_time,
                }
                for con in connections
            ]
        return {"connections": con_info}

    async def open_connection(self, request: Dict):
        host = request["host"]
        port = request["port"]
        target_node: PeerInfo = PeerInfo(host, uint16(int(port)))
        on_connect = None
        if hasattr(self.rpc_api.service, "on_connect"):
            on_connect = self.rpc_api.service.on_connect
        if getattr(self.rpc_api.service, "server", None) is None or not (
            await self.rpc_api.service.server.start_client(target_node, on_connect)
        ):
            raise ValueError("Start client failed, or server is not set")
        return {}

    async def close_connection(self, request: Dict):
        node_id = hexstr_to_bytes(request["node_id"])
        if self.rpc_api.service.server is None:
            raise aiohttp.web.HTTPInternalServerError()
        connections_to_close = [c for c in self.rpc_api.service.server.get_connections() if c.peer_node_id == node_id]
        if len(connections_to_close) == 0:
            raise ValueError(f"Connection with node_id {node_id.hex()} does not exist")
        for connection in connections_to_close:
            await connection.close()
        return {}

    async def stop_node(self, request):
        """
        Shuts down the node.
        """
        if self.stop_cb is not None:
            self.stop_cb()
        return {}

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

        raise ValueError(f"unknown_command {command}")

    async def safe_handle(self, websocket, payload):
        message = None
        try:
            message = json.loads(payload)
            self.log.debug(f"Rpc call <- {message['command']}")
            response = await self.ws_api(message)

            # Only respond if we return something from api call
            if response is not None:
                log.debug(f"Rpc response -> {message['command']}")
                # Set success to true automatically (unless it's already set)
                if "success" not in response:
                    response["success"] = True
                await websocket.send_str(format_response(message, response))

        except Exception as e:
            tb = traceback.format_exc()
            self.log.warning(f"Error while handling message: {tb}")
            if message is not None:
                error = e.args[0] if e.args else e
                res = {"success": False, "error": f"{error}"}
                await websocket.send_str(format_response(message, res))

    async def connection(self, ws):
        data = {"service": self.service_name}
        payload = create_payload("register_service", data, self.service_name, "daemon")
        await ws.send_str(payload)

        while True:
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                message = msg.data.strip()
                # self.log.info(f"received message: {message}")
                await self.safe_handle(ws, message)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                self.log.debug("Received binary data")
            elif msg.type == aiohttp.WSMsgType.PING:
                self.log.debug("Ping received")
                await ws.pong()
            elif msg.type == aiohttp.WSMsgType.PONG:
                self.log.debug("Pong received")
            else:
                if msg.type == aiohttp.WSMsgType.CLOSE:
                    self.log.debug("Closing RPC websocket")
                    await ws.close()
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.log.error("Error during receive %s" % ws.exception())
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    pass

                break

        await ws.close()

    async def connect_to_daemon(self, self_hostname: str, daemon_port: uint16):
        while True:
            session = None
            try:
                if self.shut_down:
                    break
                session = aiohttp.ClientSession()

                async with session.ws_connect(
                    f"wss://{self_hostname}:{daemon_port}",
                    autoclose=True,
                    autoping=True,
                    heartbeat=60,
                    ssl_context=self.ssl_context,
                    max_msg_size=100 * 1024 * 1024,
                ) as ws:
                    self.websocket = ws
                    await self.connection(ws)
                self.websocket = None
                await session.close()
            except aiohttp.ClientConnectorError:
                self.log.warning(f"Cannot connect to daemon at ws://{self_hostname}:{daemon_port}")
            except Exception as e:
                tb = traceback.format_exc()
                self.log.warning(f"Exception: {tb} {type(e)}")
            finally:
                if session is not None:
                    await session.close()
            await asyncio.sleep(2)


async def start_rpc_server(
    rpc_api: Any,
    self_hostname: str,
    daemon_port: uint16,
    rpc_port: uint16,
    stop_cb: Callable,
    root_path: Path,
    net_config,
    connect_to_daemon=True,
):
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    app = aiohttp.web.Application()
    rpc_server = RpcServer(rpc_api, rpc_api.service_name, stop_cb, root_path, net_config)
    rpc_server.rpc_api.service._set_state_changed_callback(rpc_server.state_changed)
    http_routes: Dict[str, Callable] = rpc_api.get_routes()

    routes = [aiohttp.web.post(route, rpc_server._wrap_http_handler(func)) for (route, func) in http_routes.items()]
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
        aiohttp.web.post("/stop_node", rpc_server._wrap_http_handler(rpc_server.stop_node)),
    ]

    app.add_routes(routes)
    if connect_to_daemon:
        daemon_connection = asyncio.create_task(rpc_server.connect_to_daemon(self_hostname, daemon_port))
    runner = aiohttp.web.AppRunner(app, access_log=None)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, self_hostname, int(rpc_port), ssl_context=rpc_server.ssl_context)
    await site.start()

    async def cleanup():
        await rpc_server.stop()
        await runner.cleanup()
        if connect_to_daemon:
            await daemon_connection

    return cleanup
