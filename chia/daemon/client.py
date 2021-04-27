import asyncio
import json
import ssl
from pathlib import Path
from typing import Any, Dict, Optional

import websockets

from chia.server.server import ssl_context_for_client
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
                    return
                decoded = json.loads(message)
                id = decoded["request_id"]

                if id in self._request_dict:
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


async def connect_to_daemon_and_validate(root_path: Path) -> Optional[DaemonProxy]:
    """
    Connect to the local daemon and do a ping to ensure that something is really
    there and running.
    """
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
        print("Daemon not started yet")
        return None
    return None
