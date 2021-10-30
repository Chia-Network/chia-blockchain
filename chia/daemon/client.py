import asyncio
import json
import ssl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

import websockets

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import load_config
from chia.util.json_util import dict_to_json_str
from chia.util.ws_message import WsRpcMessage, create_payload_dict


class DaemonProxy:
    def __init__(self, uri: str, ssl_context: Optional[ssl.SSLContext]):
        self._uri = uri
        self._request_dict: Dict[bytes32, asyncio.Event] = {}
        self.response_dict: Dict[bytes32, Any] = {}
        self.ssl_context = ssl_context

    def format_request(self, command: str, data: Dict[str, Any]) -> WsRpcMessage:
        request = create_payload_dict(command, data, "client", "daemon")
        return request

    async def start(self):
        self.websocket = await websockets.connect(self._uri, max_size=None, ssl=self.ssl_context)

        async def listener():
            while True:
                try:
                    message = await self.websocket.recv()
                except websockets.exceptions.ConnectionClosedOK:
                    return None
                decoded = json.loads(message)
                id = decoded["request_id"]

                if id in self._request_dict:
                    self.response_dict[id] = decoded
                    self._request_dict[id].set()

        asyncio.create_task(listener())
        await asyncio.sleep(1)

    async def _get(self, request: WsRpcMessage) -> WsRpcMessage:
        request_id = request["request_id"]
        self._request_dict[request_id] = asyncio.Event()
        string = dict_to_json_str(request)
        asyncio.create_task(self.websocket.send(string))

        async def timeout():
            await asyncio.sleep(30)
            if request_id in self._request_dict:
                print("Error, timeout.")
                self._request_dict[request_id].set()

        asyncio.create_task(timeout())
        await self._request_dict[request_id].wait()
        if request_id in self.response_dict:
            response = self.response_dict[request_id]
            self.response_dict.pop(request_id)
        else:
            response = None
        self._request_dict.pop(request_id)

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

    async def notify_keyring_migration_completed(self, passphrase: Optional[str]) -> WsRpcMessage:
        data: Dict[str, Any] = {"key": passphrase}
        request: WsRpcMessage = self.format_request("notify_keyring_migration_completed", data)
        response: WsRpcMessage = await self._get(request)
        return response

    async def ping(self) -> WsRpcMessage:
        request = self.format_request("ping", {})
        response = await self._get(request)
        return response

    async def close(self) -> None:
        await self.websocket.close()

    async def exit(self) -> WsRpcMessage:
        request = self.format_request("exit", {})
        return await self._get(request)


async def connect_to_daemon(self_hostname: str, daemon_port: int, ssl_context: Optional[ssl.SSLContext]) -> DaemonProxy:
    """
    Connect to the local daemon.
    """

    client = DaemonProxy(f"wss://{self_hostname}:{daemon_port}", ssl_context)
    await client.start()
    return client


async def connect_to_daemon_and_validate(root_path: Path, quiet: bool = False) -> Optional[DaemonProxy]:
    """
    Connect to the local daemon and do a ping to ensure that something is really
    there and running.
    """
    from chia.server.server import ssl_context_for_client

    try:
        net_config = load_config(root_path, "config.yaml")
        crt_path = root_path / net_config["daemon_ssl"]["private_crt"]
        key_path = root_path / net_config["daemon_ssl"]["private_key"]
        ca_crt_path = root_path / net_config["private_ssl_ca"]["crt"]
        ca_key_path = root_path / net_config["private_ssl_ca"]["key"]
        ssl_context = ssl_context_for_client(ca_crt_path, ca_key_path, crt_path, key_path)
        connection = await connect_to_daemon(net_config["self_hostname"], net_config["daemon_port"], ssl_context)
        r = await connection.ping()

        if "value" in r["data"] and r["data"]["value"] == "pong":
            return connection
    except Exception:
        if not quiet:
            print("Daemon not started yet")
        return None
    return None


@asynccontextmanager
async def acquire_connection_to_daemon(root_path: Path, quiet: bool = False):
    """
    Asynchronous context manager which attempts to create a connection to the daemon.
    The connection object (DaemonProxy) is yielded to the caller. After the caller's
    block exits scope, execution resumes in this function, wherein the connection is
    closed.
    """
    from chia.daemon.client import connect_to_daemon_and_validate

    daemon: Optional[DaemonProxy] = None
    try:
        daemon = await connect_to_daemon_and_validate(root_path, quiet=quiet)
        yield daemon  # <----
    except Exception as e:
        print(f"Exception occurred while communicating with the daemon: {e}")

    if daemon is not None:
        await daemon.close()
