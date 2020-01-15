import aiohttp
import asyncio

from typing import Dict, Optional, List
from src.util.byte_types import hexstr_to_bytes
from src.types.full_block import FullBlock
from src.types.header_block import SmallHeaderBlock
from src.types.sized_bytes import bytes32
from src.util.ints import uint16


class RpcClient:
    """
    Client to Chia RPC, connects to a local full node. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP thats provides easy access
    to the full node.
    """

    url: str
    session: aiohttp.ClientSession
    closing_task: Optional[asyncio.Task]

    @classmethod
    async def create(cls, port: uint16):
        self = cls()
        self.url = f"http://localhost:{str(port)}/"
        self.session = aiohttp.ClientSession()
        self.closing_task = None
        return self

    async def fetch(self, path, request_json):
        async with self.session.post(self.url + path, json=request_json) as response:
            response.raise_for_status()
            return await response.json()

    async def get_blockchain_state(self) -> Dict:
        response = await self.fetch("get_blockchain_state", {})
        response["tips"] = [SmallHeaderBlock.from_json(tip) for tip in response["tips"]]
        response["lca"] = SmallHeaderBlock.from_json(response["lca"])
        return response

    async def get_block(self, header_hash) -> Optional[FullBlock]:
        try:
            response = await self.fetch("get_block", {"header_hash": header_hash.hex()})
        except aiohttp.client_exceptions.ClientResponseError as e:
            if e.message == "Not Found":
                return None
            raise
        return FullBlock.from_json(response)

    async def get_header(self, header_hash) -> Optional[SmallHeaderBlock]:
        try:
            response = await self.fetch(
                "get_header", {"header_hash": header_hash.hex()}
            )
        except aiohttp.client_exceptions.ClientResponseError as e:
            if e.message == "Not Found":
                return None
            raise
        return SmallHeaderBlock.from_json(response)

    async def get_connections(self) -> List[Dict]:
        response = await self.fetch("get_connections", {})
        for connection in response:
            connection["node_id"] = hexstr_to_bytes(connection["node_id"])
        return response

    async def open_connection(self, host: str, port: int) -> Dict:
        return await self.fetch("open_connection", {"host": host, "port": int(port)})

    async def close_connection(self, node_id: bytes32) -> Dict:
        return await self.fetch("close_connection", {"node_id": node_id.hex()})

    async def stop_node(self) -> Dict:
        return await self.fetch("stop_node", {})

    async def get_pool_balances(self) -> Dict:
        response = await self.fetch("get_pool_balances", {})
        new_response = {}
        for pk, bal in response.items():
            new_response[hexstr_to_bytes(pk)] = bal
        return new_response

    async def get_heaviest_block_seen(self) -> SmallHeaderBlock:
        response = await self.fetch("get_heaviest_block_seen", {})
        return SmallHeaderBlock.from_json(response)

    def close(self):
        self.closing_task = asyncio.create_task(self.session.close())

    async def await_closed(self):
        if self.closing_task is not None:
            await self.closing_task
