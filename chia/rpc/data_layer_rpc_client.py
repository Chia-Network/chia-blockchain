from pathlib import Path
from typing import Any, Dict, List, Optional

from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64


class DataLayerRpcClient(RpcClient):
    async def create_data_store(self, fee: Optional[uint64]) -> Dict[str, Any]:
        response = await self.fetch("create_data_store", {"fee": fee})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_value(self, store_id: bytes32, key: bytes) -> Dict[str, Any]:
        response = await self.fetch("get_value", {"id": store_id.hex(), "key": key.hex()})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def update_data_store(
        self, store_id: bytes32, changelist: List[Dict[str, str]], fee: Optional[uint64]
    ) -> Dict[str, Any]:
        response = await self.fetch("batch_update", {"id": store_id.hex(), "changelist": changelist, "fee": fee})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_keys_values(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_keys_values", {"id": store_id.hex()})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_keys(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_keys", {"id": store_id.hex()})
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

    async def get_local_root(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_local_root", {"id": store_id.hex()})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def get_roots(self, store_ids: List[bytes32]) -> Dict[str, Any]:
        response = await self.fetch("get_roots", {"ids": store_ids})
        # TODO: better hinting for .fetch() (probably a TypedDict)
        return response  # type: ignore[no-any-return]

    async def subscribe(self, store_id: bytes32, urls: List[str]) -> Dict[str, Any]:
        response = await self.fetch("subscribe", {"id": store_id.hex(), "urls": urls})
        return response  # type: ignore[no-any-return]

    async def remove_subscriptions(self, store_id: bytes32, urls: List[str]) -> Dict[str, Any]:
        response = await self.fetch("remove_subscriptions", {"id": store_id.hex(), "urls": urls})
        return response  # type: ignore[no-any-return]

    async def unsubscribe(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("unsubscribe", {"id": store_id.hex()})
        return response  # type: ignore[no-any-return]

    async def add_missing_files(
        self, store_ids: Optional[List[bytes32]], override: Optional[bool], foldername: Optional[Path]
    ) -> Dict[str, Any]:
        request: Dict[str, Any] = {}
        if store_ids is not None:
            request["ids"] = [store_id.hex() for store_id in store_ids]
        if override is not None:
            request["override"] = override
        if foldername is not None:
            request["foldername"] = str(foldername)
        response = await self.fetch("add_missing_files", request)
        return response  # type: ignore[no-any-return]

    async def get_kv_diff(self, store_id: bytes32, hash_1: bytes32, hash_2: bytes32) -> Dict[str, Any]:
        response = await self.fetch(
            "get_kv_diff", {"id": store_id.hex(), "hash_1": hash_1.hex(), "hash_2": hash_2.hex()}
        )
        return response  # type: ignore[no-any-return]

    async def get_root_history(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_root_history", {"id": store_id.hex()})
        return response  # type: ignore[no-any-return]

    async def add_mirror(
        self, store_id: bytes32, urls: List[str], amount: int, fee: Optional[uint64]
    ) -> Dict[str, Any]:
        response = await self.fetch("add_mirror", {"id": store_id.hex(), "urls": urls, "amount": amount, "fee": fee})
        return response  # type: ignore[no-any-return]

    async def delete_mirror(self, coin_id: bytes32, fee: Optional[uint64]) -> Dict[str, Any]:
        response = await self.fetch("delete_mirror", {"id": coin_id.hex(), "fee": fee})
        return response  # type: ignore[no-any-return]

    async def get_mirrors(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_mirrors", {"id": store_id.hex()})
        return response  # type: ignore[no-any-return]

    async def get_subscriptions(self) -> Dict[str, Any]:
        response = await self.fetch("subscriptions", {})
        return response  # type: ignore[no-any-return]

    async def get_owned_stores(self) -> Dict[str, Any]:
        response = await self.fetch("get_owned_stores", {})
        return response  # type: ignore[no-any-return]
