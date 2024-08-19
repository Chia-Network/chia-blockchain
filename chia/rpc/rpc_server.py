from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path
from ssl import SSLContext
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Generic, List, Optional, TypeVar

from aiohttp import ClientConnectorError, ClientSession, ClientWebSocketResponse, WSMsgType, web
from typing_extensions import Protocol, final

from chia import __version__
from chia.rpc.util import wrap_http_handler
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer, ssl_context_for_client, ssl_context_for_server
from chia.server.ws_connection import WSChiaConnection
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import str2bool
from chia.util.ints import uint16
from chia.util.json_util import dict_to_json_str
from chia.util.network import WebServer, resolve
from chia.util.ws_message import WsRpcMessage, create_payload, create_payload_dict, format_response, pong

log = logging.getLogger(__name__)
max_message_size = 50 * 1024 * 1024  # 50MB


EndpointResult = Dict[str, Any]
Endpoint = Callable[[Dict[str, object]], Awaitable[EndpointResult]]
_T_RpcApiProtocol = TypeVar("_T_RpcApiProtocol", bound="RpcApiProtocol")


class StateChangedProtocol(Protocol):
    def __call__(self, change: str, change_data: Optional[Dict[str, Any]]) -> None: ...


class RpcServiceProtocol(Protocol):
    _shut_down: bool
    """Indicates a request to shut down the service.

    This is generally set internally by the class itself and not used externally.
    Consider replacing with asyncio cancellation.
    """

    @property
    def server(self) -> ChiaServer:
        """The server object that handles the common server behavior for the RPC."""
        # a property so as to be read only which allows ChiaServer to satisfy
        # Optional[ChiaServer]
        ...

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        """Report the active connections for the service.

        A default implementation is available and can be called as
        chia.rpc.rpc_server.default_get_connections()
        """
        ...

    async def on_connect(self, peer: WSChiaConnection) -> None:
        """Called when a new connection is established to the server."""
        ...

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        """Register the callable that will process state change events."""
        ...

    @contextlib.asynccontextmanager
    async def manage(self) -> AsyncIterator[None]:
        yield  # pragma: no cover


class RpcApiProtocol(Protocol):
    service_name: str
    """The name of the service.

    All lower case with underscores as needed.
    """

    def __init__(self, node: RpcServiceProtocol) -> None: ...

    @property
    def service(self) -> RpcServiceProtocol:
        """The service object that provides the specific behavior for the API."""
        # using a read-only property per https://github.com/python/mypy/issues/12990
        ...

    def get_routes(self) -> Dict[str, Endpoint]:
        """Return the mapping of endpoints to handler callables."""
        ...

    async def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]]) -> List[WsRpcMessage]:
        """Notify the state change system of a changed state."""
        ...


def default_get_connections(server: ChiaServer, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
    connections = server.get_connections(request_node_type)
    con_info = [
        {
            "type": con.connection_type,
            "local_port": con.local_port,
            "peer_host": con.peer_info.host,
            "peer_port": con.peer_info.port,
            "peer_server_port": con.peer_server_port,
            "node_id": con.peer_node_id,
            "creation_time": con.creation_time,
            "bytes_read": con.bytes_read,
            "bytes_written": con.bytes_written,
            "last_message_time": con.last_message_time,
        }
        for con in connections
    ]
    return con_info


@final
@dataclass
class RpcServer(Generic[_T_RpcApiProtocol]):
    """
    Implementation of RPC server.
    """

    rpc_api: _T_RpcApiProtocol
    stop_cb: Callable[[], None]
    service_name: str
    ssl_context: SSLContext
    ssl_client_context: SSLContext
    net_config: Dict[str, Any]
    webserver: Optional[WebServer] = None
    daemon_heartbeat: int = 300
    daemon_connection_task: Optional[asyncio.Task[None]] = None
    shut_down: bool = False
    websocket: Optional[ClientWebSocketResponse] = None
    client_session: Optional[ClientSession] = None
    prefer_ipv6: bool = False

    @classmethod
    def create(
        cls,
        rpc_api: _T_RpcApiProtocol,
        service_name: str,
        stop_cb: Callable[[], None],
        root_path: Path,
        net_config: Dict[str, Any],
        prefer_ipv6: bool,
    ) -> RpcServer[_T_RpcApiProtocol]:
        crt_path = root_path / net_config["daemon_ssl"]["private_crt"]
        key_path = root_path / net_config["daemon_ssl"]["private_key"]
        ca_cert_path = root_path / net_config["private_ssl_ca"]["crt"]
        ca_key_path = root_path / net_config["private_ssl_ca"]["key"]
        daemon_heartbeat = net_config.get("daemon_heartbeat", 300)
        ssl_context = ssl_context_for_server(ca_cert_path, ca_key_path, crt_path, key_path, log=log)
        ssl_client_context = ssl_context_for_client(ca_cert_path, ca_key_path, crt_path, key_path, log=log)
        return cls(
            rpc_api,
            stop_cb,
            service_name,
            ssl_context,
            ssl_client_context,
            net_config,
            daemon_heartbeat=daemon_heartbeat,
            prefer_ipv6=prefer_ipv6,
        )

    async def start(self, self_hostname: str, rpc_port: uint16, max_request_body_size: int) -> None:
        if self.webserver is not None:
            raise RuntimeError("RpcServer already started")
        self.webserver = await WebServer.create(
            hostname=self_hostname,
            port=rpc_port,
            max_request_body_size=max_request_body_size,
            routes=[web.post(route, wrap_http_handler(func)) for (route, func) in self._get_routes().items()],
            ssl_context=self.ssl_context,
            prefer_ipv6=self.prefer_ipv6,
        )

    def close(self) -> None:
        self.shut_down = True
        if self.webserver is not None:
            self.webserver.close()

    async def await_closed(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
        if self.client_session is not None:
            await self.client_session.close()
        if self.webserver is not None:
            await self.webserver.await_closed()
        if self.daemon_connection_task is not None:
            await self.daemon_connection_task
            self.daemon_connection_task = None

    async def _state_changed(self, change: str, change_data: Optional[Dict[str, Any]]) -> None:
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

    @property
    def listen_port(self) -> uint16:
        if self.webserver is None:
            raise RuntimeError("RpcServer is not started")
        return self.webserver.listen_port

    def _get_routes(self) -> Dict[str, Endpoint]:
        return {
            **self.rpc_api.get_routes(),
            "/get_network_info": self.get_network_info,
            "/get_connections": self.get_connections,
            "/open_connection": self.open_connection,
            "/close_connection": self.close_connection,
            "/stop_node": self.stop_node,
            "/get_routes": self.get_routes,
            "/get_version": self.get_version,
            "/healthz": self.healthz,
        }

    async def get_routes(self, request: Dict[str, Any]) -> EndpointResult:
        return {
            "success": True,
            "routes": list(self._get_routes().keys()),
        }

    async def get_network_info(self, _: Dict[str, Any]) -> EndpointResult:
        network_name = self.net_config["selected_network"]
        address_prefix = self.net_config["network_overrides"]["config"][network_name]["address_prefix"]
        genesis_challenge = self.net_config["network_overrides"]["constants"][network_name]["GENESIS_CHALLENGE"]
        return {"network_name": network_name, "network_prefix": address_prefix, "genesis_challenge": genesis_challenge}

    async def get_connections(self, request: Dict[str, Any]) -> EndpointResult:
        request_node_type: Optional[NodeType] = None
        if "node_type" in request:
            request_node_type = NodeType(request["node_type"])
        if self.rpc_api.service.server is None:
            raise ValueError("Global connections is not set")
        con_info: List[Dict[str, Any]]
        con_info = self.rpc_api.service.get_connections(request_node_type=request_node_type)
        return {"connections": con_info}

    async def open_connection(self, request: Dict[str, Any]) -> EndpointResult:
        host = request["host"]
        port = request["port"]
        target_node: PeerInfo = PeerInfo(await resolve(host, prefer_ipv6=self.prefer_ipv6), uint16(int(port)))
        on_connect = None
        if hasattr(self.rpc_api.service, "on_connect"):
            on_connect = self.rpc_api.service.on_connect
        if not await self.rpc_api.service.server.start_client(target_node, on_connect):
            return {"success": False, "error": f"could not connect to {target_node}"}
        return {"success": True}

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
            "success": True,
        }

    async def get_version(self, request: Dict[str, Any]) -> EndpointResult:
        return {
            "version": __version__,
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
                    log.error("Error during receive %s", ws.exception())
                elif msg.type == WSMsgType.CLOSED:
                    pass

                break

    def connect_to_daemon(self, self_hostname: str, daemon_port: uint16) -> None:
        if self.daemon_connection_task is not None:
            raise RuntimeError("Already connected to the daemon")

        async def inner() -> None:
            while not self.shut_down:
                try:
                    self.client_session = ClientSession()
                    self.websocket = await self.client_session.ws_connect(
                        f"wss://{self_hostname}:{daemon_port}",
                        autoclose=True,
                        autoping=True,
                        heartbeat=self.daemon_heartbeat,
                        ssl=self.ssl_client_context,
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

        self.daemon_connection_task = asyncio.create_task(inner())


async def start_rpc_server(
    rpc_api: _T_RpcApiProtocol,
    self_hostname: str,
    daemon_port: uint16,
    rpc_port: uint16,
    stop_cb: Callable[[], None],
    root_path: Path,
    net_config: Dict[str, object],
    connect_to_daemon: bool = True,
    max_request_body_size: Optional[int] = None,
) -> RpcServer[_T_RpcApiProtocol]:
    """
    Starts an HTTP server with the following RPC methods, to be used by local clients to
    query the node.
    """
    try:
        if max_request_body_size is None:
            max_request_body_size = 1024**2

        prefer_ipv6 = str2bool(str(net_config.get("prefer_ipv6", False)))

        rpc_server = RpcServer.create(
            rpc_api, rpc_api.service_name, stop_cb, root_path, net_config, prefer_ipv6=prefer_ipv6
        )
        rpc_server.rpc_api.service._set_state_changed_callback(rpc_server.state_changed)
        await rpc_server.start(self_hostname, rpc_port, max_request_body_size)

        if connect_to_daemon:
            rpc_server.connect_to_daemon(self_hostname, daemon_port)

        return rpc_server
    except Exception:
        tb = traceback.format_exc()
        log.error(f"Starting RPC server failed. Exception {tb}")
        raise
