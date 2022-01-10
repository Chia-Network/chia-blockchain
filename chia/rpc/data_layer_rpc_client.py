from typing import Any, Dict

from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.sized_bytes import bytes32


class DataLayerRpcClient(RpcClient):
    async def create_data_store(self) -> Dict[str, Any]:
        response = await self.fetch("create_data_store", {})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_value(self, tree_id: bytes32, key: bytes) -> Dict[str, Any]:
        response = await self.fetch("get_value", {"id": tree_id.hex(), "key": key.hex()})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def update_data_store(self, tree_id: bytes32, changelist: Dict[str, str]) -> Dict[str, Any]:
        response = await self.fetch("update_data_store", {"id": tree_id.hex(), "changelist": changelist})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_keys_values(self, tree_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_keys_values", {"id": tree_id.hex()})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response

    async def get_ancestors(self, tree_id: bytes32, hash: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_ancestors", {"id": tree_id.hex(), "hash": hash})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response
