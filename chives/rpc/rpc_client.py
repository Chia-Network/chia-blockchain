import asyncio
from ssl import SSLContext
from typing import Dict, List, Optional, Any

import aiohttp

from chia.server.server import ssl_context_for_client
from chia.server.ssl_context import private_ssl_ca_paths
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16


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
    ssl_context: Optional[SSLContext]

    @classmethod
    async def create(cls, self_hostname: str, port: uint16, root_path, net_config):
        self = cls()
        self.url = f"https://{self_hostname}:{str(port)}/"
        self.session = aiohttp.ClientSession()
        ca_crt_path, ca_key_path = private_ssl_ca_paths(root_path, net_config)
        crt_path = root_path / net_config["daemon_ssl"]["private_crt"]
        key_path = root_path / net_config["daemon_ssl"]["private_key"]
        self.ssl_context = ssl_context_for_client(ca_crt_path, ca_key_path, crt_path, key_path)
        self.closing_task = None
        return self

    async def fetch(self, path, request_json) -> Any:
        async with self.session.post(self.url + path, json=request_json, ssl_context=self.ssl_context) as response:
            response.raise_for_status()
            res_json = await response.json()
            if not res_json["success"]:
                raise ValueError(res_json)
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
