import aiohttp
import asyncio

from typing import Dict, Optional, List
from src.util.byte_types import hexstr_to_bytes
from src.types.sized_bytes import bytes32
from src.util.ints import uint16


class RpcClient:
    """
    Client to Chia RPC, connects to a local service. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP thats provides easy access
    to the full node.
    """

    url: str
    session: aiohttp.ClientSession
    closing_task: Optional[asyncio.Task]

    @classmethod
    async def create(cls, self_hostname: str, port: uint16):
        self = cls()
        self.url = f"http://{self_hostname}:{str(port)}/"
        self.session = aiohttp.ClientSession()
        self.closing_task = None
        return self

    async def fetch(self, path, request_json):
        async with self.session.post(self.url + path, json=request_json) as response:
            response.raise_for_status()
            res_json = await response.json()
            if not res_json["success"]:
                if "error" in res_json:
                    raise Exception(res_json["error"])
                else:
                    raise Exception()
            return res_json

    async def get_connections(self) -> List[Dict]:
        response = await self.fetch("get_connections", {})
        for connection in response["connections"]:
            connection["node_id"] = hexstr_to_bytes(connection["node_id"])
        return response["connections"]

    async def open_connection(self, host: str, port: int) -> Dict:
        return await self.fetch("open_connection", {"host": host, "port": int(port)})

    async def close_connection(self, node_id: bytes32) -> Dict:
        return await self.fetch("close_connection", {"node_id": node_id.hex()})

    async def stop_node(self) -> Dict:
        return await self.fetch("stop_node", {})

    def close(self):
        self.closing_task = asyncio.create_task(self.session.close())

    async def await_closed(self):
        if self.closing_task is not None:
            await self.closing_task
