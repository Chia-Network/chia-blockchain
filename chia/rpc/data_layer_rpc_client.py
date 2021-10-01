from typing import Dict

from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.sized_bytes import bytes32


class DataLayerRpcClient(RpcClient):
    async def create_table(self, table: bytes32, name: str):
        response = await self.fetch("create_table", {"table": table.hex(), "name": name})
        return response

    async def get_row(self, table: bytes32, row_hash: bytes32) -> Dict:
        response = await self.fetch("get_row", {"table": table.hex(), "row_hash": row_hash.hex()})
        return response

    async def updat_table(self, table: bytes32, changelist: str) -> Dict:
        print("update table")
        response = await self.fetch(
            "update_table",
            {"table": table.hex(), "changelist": changelist},
        )
        return response

    async def get_table_state(self, table: bytes32) -> bytes32:
        pass
