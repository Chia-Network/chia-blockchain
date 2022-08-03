from __future__ import annotations

import asyncio
import json
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path
from ssl import SSLContext
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from aiohttp import ClientConnectorError, ClientSession, ClientWebSocketResponse, WSMsgType, web
from typing_extensions import final

from chia.rpc.util import wrap_http_handler
from chia.server.outbound_message import NodeType
from chia.server.server import ssl_context_for_client, ssl_context_for_server
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16
from chia.util.json_util import dict_to_json_str
from chia.util.network import select_port
from chia.util.ws_message import WsRpcMessage, create_payload, create_payload_dict, format_response, pong

log = logging.getLogger(__name__)
max_message_size = 50 * 1024 * 1024  # 50MB


EndpointResult = Dict[str, Any]
Endpoint = Callable[[Dict[str, object]], Awaitable[EndpointResult]]


@final
@dataclass
class RpcServer:
    """
    Implementation of RPC server.
    """

    rpc_api: Any
    stop_cb: Callable[[], None]
    service_name: str
    ssl_context: SSLContext
    ssl_client_context: SSLContext
    shut_down: bool = False
    websocket: Optional[ClientWebSocketResponse] = None
    client_session: Optional[ClientSession] = None

    @classmethod
    def create(
        cls, rpc_api: Any, service_name: str, stop_cb: Callable[[], None], root_path: Path, net_config: Dict[str, Any]
    ) -> RpcServer:
        crt_path = root_path / net_config["daemon_ssl"]["private_crt"]
        key_path = root_path / net_config["daemon_ssl"]["private_key"]
        ca_cert_path = root_path / net_config["private_ssl_ca"]["crt"]
        ca_key_path = root_path / net_config["private_ssl_ca"]["key"]
        ssl_context = ssl_context_for_server(ca_cert_path, ca_key_path, crt_path, key_path, log=log)
        ssl_client_context = ssl_context_for_client(ca_cert_path, ca_key_path, crt_path, key_path, log=log)
        return cls(rpc_api, stop_cb, service_name, ssl_context, ssl_client_context)

    async def stop(self) -> None:
        self.shut_down = True
        if self.websocket is not None:
            await self.websocket.close()
        if self.client_session is not None:
            await self.client_session.close()

    async def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]] = None) -> None:
        if self.websocket is None or self.websocket.closed:
            return None
        payloads: List[WsRpcMessage] = await self.rpc_api._state_changed(change, change_data)

        if change == "add_connection" or change == "close_connection" or change == "peer_changed_peak":
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
            if self.websocket is None or self.websocket.closed:
                return None
            try:
                await self.websocket.send_str(dict_to_json_str(payload))
            except Exception:
                tb = traceback.format_exc()
                log.warning(f"Sending data failed. Exception {tb}.")

    def state_changed(self, change: str, change_data: Optional[Dict[str, Any]] = None) -> None:
        if self.websocket is None or self.websocket.closed:
            return None
        asyncio.create_task(self._state_changed(change, change_data))

    def get_routes(self) -> Dict[str, Endpoint]:
        return {
            **self.rpc_api.get_routes(),
            "/get_connections": self.get_connections,
            "/open_connection": self.open_connection,
            "/close_connection": self.close_connection,
            "/stop_node": self.stop_node,
            "/get_routes": self._get_routes,
            "/healthz": self.healthz,
        }

    async def _get_routes(self, request: Dict[str, Any]) -> EndpointResult:
        return {
            "success": "true",
            "routes": list(self.get_routes().keys()),
        }

    async def get_connections(self, request: Dict[str, Any]) -> EndpointResult:
        request_node_type: Optional[NodeType] = None
        if "node_type" in request:
            request_node_type = NodeType(request["node_type"])
        if self.rpc_api.service.server is None:
            raise ValueError("Global connections is not set")
        if self.rpc_api.service.server._local_type is NodeType.FULL_NODE:
            # TODO add peaks for peers
            connections = self.rpc_api.service.server.get_connections(request_node_type)
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
            connections = self.rpc_api.service.server.get_connections(request_node_type)
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

    async def open_connection(self, request: Dict[str, Any]) -> EndpointResult:
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

    async def close_connection(self, request: Dict[str, Any]) -> EndpointResult:
        node_id = hexstr_to_bytes(request["node_id"])
        if self.rpc_api.service.server is None:
            raise web.HTTPInternalServerError()
        connections_to_close = [c for c in self.rpc_api.service.server.get_connections() if c.peer_node_id == node_id]
        if len(connections_to_close) == 0:
            raise ValueError(f"Connection with node_id {node_id.hex()} does not exist")
        for connection in connections_to_close:
            await connection.close()
        return {}

    async def stop_node(self, request: Dict[str, Any]) -> EndpointResult:
        """
        Shuts down the node.
        """
        if self.stop_cb is not None:
            self.stop_cb()
        return {}

    async def healthz(self, request: Dict[str, Any]) -> EndpointResult:
        return {
            "success": "true",
        }

    async def ws_api(self, message: WsRpcMessage) -> Optional[Dict[str, object]]:
        """
        This function gets called when new message is received via websocket.
        """

        command = message["command"]
        if message["ack"]:
            return None

        data: Dict[str, object] = {}
        if "data" in message:
            data = message["data"]
        if command == "ping":
            return pong()

        f_internal: Optional[Endpoint] = getattr(self, command, None)
        if f_internal is not None:
            return await f_internal(data)
        f_rpc_api: Optional[Endpoint] = getattr(self.rpc_api, command, None)
        if f_rpc_api is not None:
            return await f_rpc_api(data)

        raise ValueError(f"unknown_command {command}")

    async def safe_handle(self, websocket: ClientWebSocketResponse, payload: str) -> None:
        message = None
        try:
            message = json.loads(payload)
            log.debug(f"Rpc call <- {message['command']}")
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
            log.warning(f"Error while handling message: {tb}")
            if message is not None:
                error = e.args[0] if e.args else e
                res = {"success": False, "error": f"{error}"}
                await websocket.send_str(format_response(message, res))

    async def connection(self, ws: ClientWebSocketResponse) -> None:
        data = {"service": self.service_name}
        payload = create_payload("register_service", data, self.service_name, "daemon")
        await ws.send_str(payload)

        while True:
            # ClientWebSocketReponse::receive() internally handles PING, PONG, and CLOSE messages
            msg = await ws.receive()
            if msg.type == WSMsgType.TEXT:
                message = msg.data.strip()
                # log.info(f"received message: {message}")
                await self.safe_handle(ws, message)
            elif msg.type == WSMsgType.BINARY:
                log.debug("Received binary data")
            else:
                if msg.type == WSMsgType.ERROR:
                    log.error("Error during receive %s" % ws.exception())
                elif msg.type == WSMsgType.CLOSED:
                    pass

                break

    async def connect_to_daemon(self, self_hostname: str, daemon_port: uint16) -> None:
        while not self.shut_down:
            try:
                self.client_session = ClientSession()
                self.websocket = await self.client_session.ws_connect(
                    f"wss://{self_hostname}:{daemon_port}",
                    autoclose=True,
                    autoping=True,
                    heartbeat=60,
                    ssl_context=self.ssl_client_context,
                    max_msg_size=max_message_size,
                )
                await self.connection(self.websocket)
            except ClientConnectorError:
                log.warning(f"Cannot connect to daemon at ws://{self_hostname}:{daemon_port}")
            except Exception as e:
                tb = traceback.format_exc()
                log.warning(f"Exception: {tb} {type(e)}")
            if self.websocket is not None:
                await self.websocket.close()
            if self.client_session is not None:
                await self.client_session.close()
            self.websocket = None
            self.client_session = None
            await asyncio.sleep(2)


async def start_rpc_server(
    rpc_api: Any,
    self_hostname: str,
    daemon_port: uint16,
    rpc_port: uint16,
    stop_cb: Callable[[], None],
    root_path: Path,
    net_config: Dict[str, object],
    connect_to_daemon: bool = True,
    max_request_body_size: Optional[int] = None,
    name: str = "rpc_server",
) -> Tuple[Callable[[], Awaitable[None]], uint16]:
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    try:
        if max_request_body_size is None:
            max_request_body_size = 1024 ** 2
        app = web.Application(client_max_size=max_request_body_size)
        rpc_server = RpcServer.create(rpc_api, rpc_api.service_name, stop_cb, root_path, net_config)
        rpc_server.rpc_api.service._set_state_changed_callback(rpc_server.state_changed)
        app.add_routes([web.post(route, wrap_http_handler(func)) for (route, func) in rpc_server.get_routes().items()])
        if connect_to_daemon:
            daemon_connection = asyncio.create_task(rpc_server.connect_to_daemon(self_hostname, daemon_port))
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()

        site = web.TCPSite(runner, self_hostname, int(rpc_port), ssl_context=rpc_server.ssl_context)
        await site.start()

        #
        # On a dual-stack system, we want to get the (first) IPv4 port unless
        # prefer_ipv6 is set in which case we use the IPv6 port
        #
        if rpc_port == 0:
            rpc_port = select_port(root_path, runner.addresses)

        async def cleanup() -> None:
            await rpc_server.stop()
            await runner.cleanup()
            if connect_to_daemon:
                await daemon_connection

        return cleanup, rpc_port
    except Exception:
        tb = traceback.format_exc()
        log.error(f"Starting RPC server failed. Exception {tb}.")
        raise
