from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from chia.data_layer.data_layer_util import ClearPendingRootsRequest
from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64


class DataLayerRpcClient(RpcClient):
    async def create_data_store(self, fee: Optional[uint64]) -> Dict[str, Any]:
        response = await self.fetch("create_data_store", {"fee": fee})
        return response

    async def get_value(self, store_id: bytes32, key: bytes, root_hash: Optional[bytes32]) -> Dict[str, Any]:
        request: Dict[str, Any] = {"id": store_id.hex(), "key": key.hex()}
        if root_hash is not None:
            request["root_hash"] = root_hash.hex()
        response = await self.fetch("get_value", request)
        return response

    async def update_data_store(
        self, store_id: bytes32, changelist: List[Dict[str, str]], fee: Optional[uint64]
    ) -> Dict[str, Any]:
        response = await self.fetch("batch_update", {"id": store_id.hex(), "changelist": changelist, "fee": fee})
        return response

    async def get_keys_values(self, store_id: bytes32, root_hash: Optional[bytes32]) -> Dict[str, Any]:
        request: Dict[str, Any] = {"id": store_id.hex()}
        if root_hash is not None:
            request["root_hash"] = root_hash.hex()
        response = await self.fetch("get_keys_values", request)
        return response

    async def get_keys(self, store_id: bytes32, root_hash: Optional[bytes32]) -> Dict[str, Any]:
        request: Dict[str, Any] = {"id": store_id.hex()}
        if root_hash is not None:
            request["root_hash"] = root_hash.hex()
        response = await self.fetch("get_keys", request)
        return response

    async def get_ancestors(self, store_id: bytes32, hash: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_ancestors", {"id": store_id.hex(), "hash": hash})
        return response

    async def get_root(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_root", {"id": store_id.hex()})
        return response

    async def get_local_root(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_local_root", {"id": store_id.hex()})
        return response

    async def get_roots(self, store_ids: List[bytes32]) -> Dict[str, Any]:
        response = await self.fetch("get_roots", {"ids": store_ids})
        return response

    async def subscribe(self, store_id: bytes32, urls: List[str]) -> Dict[str, Any]:
        response = await self.fetch("subscribe", {"id": store_id.hex(), "urls": urls})
        return response

    async def remove_subscriptions(self, store_id: bytes32, urls: List[str]) -> Dict[str, Any]:
        response = await self.fetch("remove_subscriptions", {"id": store_id.hex(), "urls": urls})
        return response

    async def unsubscribe(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("unsubscribe", {"id": store_id.hex()})
        return response

    async def add_missing_files(
        self, store_ids: Optional[List[bytes32]], overwrite: Optional[bool], foldername: Optional[Path]
    ) -> Dict[str, Any]:
        request: Dict[str, Any] = {}
        if store_ids is not None:
            request["ids"] = [store_id.hex() for store_id in store_ids]
        if overwrite is not None:
            request["overwrite"] = overwrite
        if foldername is not None:
            request["foldername"] = str(foldername)
        response = await self.fetch("add_missing_files", request)
        return response

    async def get_kv_diff(self, store_id: bytes32, hash_1: bytes32, hash_2: bytes32) -> Dict[str, Any]:
        response = await self.fetch(
            "get_kv_diff", {"id": store_id.hex(), "hash_1": hash_1.hex(), "hash_2": hash_2.hex()}
        )
        return response

    async def get_root_history(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_root_history", {"id": store_id.hex()})
        return response

    async def add_mirror(
        self, store_id: bytes32, urls: List[str], amount: int, fee: Optional[uint64]
    ) -> Dict[str, Any]:
        response = await self.fetch("add_mirror", {"id": store_id.hex(), "urls": urls, "amount": amount, "fee": fee})
        return response

    async def delete_mirror(self, coin_id: bytes32, fee: Optional[uint64]) -> Dict[str, Any]:
        response = await self.fetch("delete_mirror", {"coin_id": coin_id.hex(), "fee": fee})
        return response

    async def get_mirrors(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_mirrors", {"id": store_id.hex()})
        return response

    async def get_subscriptions(self) -> Dict[str, Any]:
        response = await self.fetch("subscriptions", {})
        return response

    async def get_owned_stores(self) -> Dict[str, Any]:
        response = await self.fetch("get_owned_stores", {})
        return response

    async def get_sync_status(self, store_id: bytes32) -> Dict[str, Any]:
        response = await self.fetch("get_sync_status", {"id": store_id.hex()})
        return response

    async def check_plugins(self) -> Dict[str, Any]:
        response = await self.fetch("check_plugins", {})
        return response

    async def clear_pending_roots(self, store_id: bytes32) -> Dict[str, Any]:
        request = ClearPendingRootsRequest(store_id=store_id)
        response = await self.fetch("clear_pending_roots", request.marshal())
        return response
