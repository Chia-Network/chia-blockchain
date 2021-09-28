from typing import Dict

from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.sized_bytes import bytes32


class DataLayerRpcClient(RpcClient):
    async def create_table(self, table: bytes32, name: str) -> Dict:
        response = await self.fetch("create_table", {"table": table.hex(), "name": name})
        return response

    async def get_row(self, table: bytes32, row_hash: bytes32) -> Dict:
        response = await self.fetch("get_row", {"table": table.hex(), "row_hash": row_hash.hex()})
        return response

    async def insert_row(self, table: bytes32, row_data: bytes) -> Dict:
        response = await self.fetch(
            "update",
            {"table": table.hex(), "changelist": [{"action": "insert", "row_data": row_data.hex()}]},
        )
        return response
