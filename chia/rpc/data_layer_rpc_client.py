from typing import Dict

from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.sized_bytes import bytes32


class DataLayerRpcClient(RpcClient):
    async def create_kv_store(self, tree_id: bytes32):
        # todo tree id should probably be a running id of all trees
        # response = await self.fetch("create_kv_store", {"tree_id": tree_id})
        response = await self.fetch("create_kv_store", {})
        return response

    async def get_value(self, tree_id: bytes32, key: bytes) -> Dict:
        return await self.fetch("get_value", {"tree_id": tree_id, "key": key})

    async def update_kv_store(self, tree_id: bytes32, changelist: str) -> Dict:
        response = await self.fetch(
            "update_kv_store",
            {"tree_id": tree_id, "changelist": changelist},
        )
        return response

    async def get_tree_state(self, tree_id: bytes32) -> bytes32:
        pass
