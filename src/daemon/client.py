import json
from asyncio import Event, ensure_future
from typing import Dict, Any

import websockets
import asyncio

from src.types.sized_bytes import bytes32
from src.util.ws_message import create_payload
from src.util.json_util import dict_to_json_str


class DaemonProxy:
    def __init__(self, uri):
        self._uri = uri
        self._request_dict: Dict[bytes32, Event] = {}
        self.response_dict: Dict[bytes32, Any] = {}
        self.websocket = None

    def format_request(self, command, data=None):
        request = create_payload(command, data, "client", "daemon", False)
        return request

    async def start(self):
        self.websocket = await websockets.connect(self._uri)

        async def listener():
            while True:
                message = await self.websocket.recv()
                decoded = json.loads(message)
                id = decoded["request_id"]

                if id in self._request_dict:
                    if id in self._request_dict:
                        self.response_dict[id] = decoded
                        self._request_dict[id].set()

        asyncio.create_task(listener())
        await asyncio.sleep(1)

    async def _get(self, request):
        request_id = request["request_id"]
        self._request_dict[request_id] = Event()
        string = dict_to_json_str(request)
        ensure_future(self.websocket.send(string))

        async def timeout():
            await asyncio.sleep(30)
            if request_id in self._request_dict:
                print("Error, timeout.")
                self._request_dict[request_id].set()

        ensure_future(timeout())
        await self._request_dict[request_id].wait()
        if request_id in self.response_dict:
            response = self.response_dict[request_id]
            self.response_dict.pop(request_id)
        else:
            response = None
        self._request_dict.pop(request_id)

        return response

    async def start_service(self, service_name):
        data = {"service": service_name}
        request = self.format_request("start_service", data)
        response = await self._get(request)
        return response

    async def stop_service(self, service_name, delay_before_kill=15):
        data = {"service": service_name}
        request = self.format_request("stop_service", data)
        response = await self._get(request)
        return response

    async def is_running(self, service_name):
        data = {"service": service_name}
        request = self.format_request("is_running", data)
        response = await self._get(request)
        is_running = response["data"]["is_running"]
        return is_running

    async def ping(self):
        request = self.format_request("ping")
        response = await self._get(request)
        return response

    async def exit(self):
        request = self.format_request("exit", {})
        return await self._get(request)


async def connect_to_daemon():
    """
    Connect to the local daemon.
    """

    client = DaemonProxy("ws://127.0.0.1:55400")
    await client.start()
    return client


async def connect_to_daemon_and_validate(root_path):
    """
    Connect to the local daemon and do a ping to ensure that something is really
    there and running.
    """
    try:
        connection = await connect_to_daemon()
        r = await connection.ping()

        if r["data"]["value"] == "pong":
            return connection
    except Exception as ex:
        print(f"Exception {ex}")
    return None
