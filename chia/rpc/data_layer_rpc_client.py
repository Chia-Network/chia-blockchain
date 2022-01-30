from typing import Any, Dict, List

from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64


class DataLayerRpcClient(RpcClient):
    async def create_data_store(self, fee: uint64) -> Dict[str, Any]:
        response = await self.fetch("create_data_store", {"fee": fee})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_value(self, store_id: bytes32, key: bytes) -> Dict[str, Any]:
        response = await self.fetch("get_value", {"id": store_id.hex(), "key": key.hex()})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def update_data_store(self, store_id: bytes32, changelist: Dict[str, str], fee: uint64) -> Dict[str, Any]:
        response = await self.fetch("batch_update", {"id": store_id.hex(), "changelist": changelist, "fee": fee})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_keys_values(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_keys_values", {"id": store_id.hex()})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_ancestors(self, store_id: bytes32, hash: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_ancestors", {"id": store_id.hex(), "hash": hash})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_root(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_root", {"id": store_id.hex()})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_roots(self, store_ids: List[bytes32]) -> Dict[str, Any]:
        response = await self.fetch("get_roots", {"ids": store_ids})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]
