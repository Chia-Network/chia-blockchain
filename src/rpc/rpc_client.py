import aiohttp

from src.util.byte_types import hexstr_to_bytes
from src.types.full_block import FullBlock
from src.types.header import Header
from src.types.sized_bytes import bytes32
from src.util.ints import uint16


class RpcClient:
    url: str
    session: aiohttp.ClientSession

    @classmethod
    async def create(cls, port: uint16):
        self = cls()
        self.url = f"http://localhost:{str(port)}/"
        self.session = aiohttp.ClientSession()
        return self

    async def fetch(self, path, request_json):
        async with self.session.post(self.url + path, json=request_json) as response:
            response.raise_for_status()
            return await response.json()

    async def get_blockchain_state(self):
        response = await self.fetch("get_blockchain_state", {})
        tips = [{"height": tip["height"], "header_hash": hexstr_to_bytes(tip["header_hash"])}
                for tip in response["tips"]]
        lca = {"height": response["lca"]["height"], "header_hash": hexstr_to_bytes(response["lca"]["header_hash"])}
        return {"tips": tips, "lca": lca, "sync_mode": response["sync_mode"]}

    async def get_block(self, header_hash):
        response = await self.fetch("get_block", {"header_hash": header_hash.hex()})
        return FullBlock.from_json(response)

    async def get_header(self, header_hash):
        response = await self.fetch("get_header", {"header_hash": header_hash.hex()})
        return Header.from_json(response)

    async def get_connections(self):
        response = await self.fetch("get_connections", {})
        for connection in response:
            connection["node_id"] = hexstr_to_bytes(connection["node_id"])
        return response

    async def open_connection(self, host: str, port: int):
        response = await self.fetch("open_connection", {"host": host, "port": int(port)})
        return response

    async def close_connection(self, node_id: bytes32):
        response = await self.fetch("close_connection", {"node_id": node_id.hex()})
        return response

    async def close(self):
        await self.session.close()
