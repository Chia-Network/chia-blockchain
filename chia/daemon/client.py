from __future__ import annotations

import asyncio
import json
import ssl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

import aiohttp

from chia.util.json_util import dict_to_json_str
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class DaemonProxy:
    def __init__(
        self,
        uri: str,
        ssl_context: Optional[ssl.SSLContext],
        heartbeat: int,
        max_message_size: int = 50 * 1000 * 1000,
    ):
        self._uri = uri
        self._request_dict: Dict[str, asyncio.Event] = {}
        self.response_dict: Dict[str, WsRpcMessage] = {}
        self.ssl_context = ssl_context
        self.heartbeat = heartbeat
        self.client_session: Optional[aiohttp.ClientSession] = None
        self.websocket: Optional[aiohttp.ClientWebSocketResponse] = None
        self.max_message_size = max_message_size

    def format_request(self, command: str, data: Dict[str, Any]) -> WsRpcMessage:
        request = create_payload_dict(command, data, "client", "daemon")
        return request

    async def start(self) -> None:
        try:
            self.client_session = aiohttp.ClientSession()
            self.websocket = await self.client_session.ws_connect(
                self._uri,
                autoclose=True,
                autoping=True,
                heartbeat=self.heartbeat,
                ssl_context=self.ssl_context,
                max_msg_size=self.max_message_size,
            )
        except Exception:
            await self.close()
            raise

        async def listener_task() -> None:
            try:
                await self.listener()
            finally:
                await self.close()

        asyncio.create_task(listener_task())
        await asyncio.sleep(1)

    async def listener(self) -> None:
        if self.websocket is None:
            raise TypeError("Websocket is None in listener!")
        while True:
            message = await self.websocket.receive()
            if message.type == aiohttp.WSMsgType.TEXT:
                decoded: WsRpcMessage = json.loads(message.data)
                request_id = decoded["request_id"]

                if request_id in self._request_dict:
                    self.response_dict[request_id] = decoded
                    self._request_dict[request_id].set()
            else:
                return None

    async def _get(self, request: WsRpcMessage) -> WsRpcMessage:
        request_id = request["request_id"]
        self._request_dict[request_id] = asyncio.Event()
        string = dict_to_json_str(request)
        if self.websocket is None or self.websocket.closed:
            raise Exception("Websocket is not connected")
        asyncio.create_task(self.websocket.send_str(string))
        try:
            await asyncio.wait_for(self._request_dict[request_id].wait(), timeout=30)
            self._request_dict.pop(request_id)
            response: WsRpcMessage = self.response_dict[request_id]
            self.response_dict.pop(request_id)
            return response
        except asyncio.TimeoutError:
            self._request_dict.pop(request_id)
            raise Exception(f"No response from daemon for request_id: {request_id}")

    async def get_version(self) -> WsRpcMessage:
        data: Dict[str, Any] = {}
        request = self.format_request("get_version", data)
        response = await self._get(request)
        return response

    async def start_service(self, service_name: str) -> WsRpcMessage:
        data = {"service": service_name}
        request = self.format_request("start_service", data)
        response = await self._get(request)
        return response

    async def stop_service(self, service_name: str, delay_before_kill: int = 15) -> WsRpcMessage:
        data = {"service": service_name}
        request = self.format_request("stop_service", data)
        response = await self._get(request)
        return response

    async def is_running(self, service_name: str) -> bool:
        data = {"service": service_name}
        request = self.format_request("is_running", data)
        response = await self._get(request)
        if "is_running" in response["data"]:
            return bool(response["data"]["is_running"])
        return False

    async def is_keyring_locked(self) -> bool:
        data: Dict[str, Any] = {}
        request = self.format_request("is_keyring_locked", data)
        response = await self._get(request)
        if "is_keyring_locked" in response["data"]:
            return bool(response["data"]["is_keyring_locked"])
        return False

    async def unlock_keyring(self, passphrase: str) -> WsRpcMessage:
        data = {"key": passphrase}
        request = self.format_request("unlock_keyring", data)
        response = await self._get(request)
        return response

    async def ping(self) -> WsRpcMessage:
        request = self.format_request("ping", {})
        response = await self._get(request)
        return response

    async def close(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
        if self.client_session is not None:
            await self.client_session.close()

    async def exit(self) -> WsRpcMessage:
        request = self.format_request("exit", {})
        return await self._get(request)


async def connect_to_daemon(
    self_hostname: str, daemon_port: int, max_message_size: int, ssl_context: ssl.SSLContext, heartbeat: int
) -> DaemonProxy:
    """
    Connect to the local daemon.
    """

    client = DaemonProxy(
        f"wss://{self_hostname}:{daemon_port}",
        ssl_context=ssl_context,
        max_message_size=max_message_size,
        heartbeat=heartbeat,
    )
    await client.start()
    return client


async def connect_to_daemon_and_validate(
    root_path: Path, config: Dict[str, Any], quiet: bool = False
) -> Optional[DaemonProxy]:
    """
    Connect to the local daemon and do a ping to ensure that something is really
    there and running.
    """
    from chia.server.server import ssl_context_for_client

    try:
        daemon_max_message_size = config.get("daemon_max_message_size", 50 * 1000 * 1000)
        daemon_heartbeat = config.get("daemon_heartbeat", 300)
        crt_path = root_path / config["daemon_ssl"]["private_crt"]
        key_path = root_path / config["daemon_ssl"]["private_key"]
        ca_crt_path = root_path / config["private_ssl_ca"]["crt"]
        ca_key_path = root_path / config["private_ssl_ca"]["key"]
        ssl_context = ssl_context_for_client(ca_crt_path, ca_key_path, crt_path, key_path)
        connection = await connect_to_daemon(
            config["self_hostname"],
            config["daemon_port"],
            max_message_size=daemon_max_message_size,
            ssl_context=ssl_context,
            heartbeat=daemon_heartbeat,
        )
        r = await connection.ping()

        if "value" in r["data"] and r["data"]["value"] == "pong":
            return connection
    except Exception:
        if not quiet:
            print("Daemon not started yet")
        return None
    return None


@asynccontextmanager
async def acquire_connection_to_daemon(
    root_path: Path, config: Dict[str, Any], quiet: bool = False
) -> AsyncIterator[Optional[DaemonProxy]]:
    """
    Asynchronous context manager which attempts to create a connection to the daemon.
    The connection object (DaemonProxy) is yielded to the caller. After the caller's
    block exits scope, execution resumes in this function, wherein the connection is
    closed.
    """

    daemon: Optional[DaemonProxy] = None
    try:
        daemon = await connect_to_daemon_and_validate(root_path, config, quiet=quiet)
        yield daemon  # <----
    except Exception as e:
        print(f"Exception occurred while communicating with the daemon: {e}")

    if daemon is not None:
        await daemon.close()
