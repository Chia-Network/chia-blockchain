from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.data_layer.data_layer_util import ClearPendingRootsRequest
from chia.rpc.rpc_client import RpcClient


class DataLayerRpcClient(RpcClient):
    async def create_data_store(self, fee: Optional[uint64], verbose: bool) -> dict[str, Any]:
        response = await self.fetch("create_data_store", {"fee": fee, "verbose": verbose})
        return response

    async def wallet_log_in(self, fingerprint: int) -> dict[str, Any]:
        request: dict[str, Any] = {"fingerprint": fingerprint}
        response = await self.fetch("wallet_log_in", request)
        return response

    async def get_value(self, store_id: bytes32, key: bytes, root_hash: Optional[bytes32]) -> dict[str, Any]:
        request: dict[str, Any] = {"id": store_id.hex(), "key": key.hex()}
        if root_hash is not None:
            request["root_hash"] = root_hash.hex()
        response = await self.fetch("get_value", request)
        return response

    async def update_data_store(
        self, store_id: bytes32, changelist: list[dict[str, str]], fee: Optional[uint64], submit_on_chain: bool = True
    ) -> dict[str, Any]:
        response = await self.fetch(
            "batch_update",
            {
                "id": store_id.hex(),
                "changelist": changelist,
                "fee": fee,
                "submit_on_chain": submit_on_chain,
            },
        )
        return response

    async def update_multiple_stores(
        self, store_updates: list[dict[str, Any]], fee: Optional[uint64], submit_on_chain: bool = True
    ) -> dict[str, Any]:
        response = await self.fetch(
            "multistore_batch_update",
            {
                "store_updates": store_updates,
                "fee": fee,
                "submit_on_chain": submit_on_chain,
            },
        )
        return response

    async def submit_pending_root(self, store_id: bytes32, fee: Optional[uint64]) -> dict[str, Any]:
        response = await self.fetch("submit_pending_root", {"id": store_id.hex(), "fee": fee})
        return response

    async def submit_all_pending_roots(self, fee: Optional[uint64]) -> dict[str, Any]:
        response = await self.fetch("submit_all_pending_roots", {"fee": fee})
        return response

    async def get_keys_values(
        self, store_id: bytes32, root_hash: Optional[bytes32], page: Optional[int], max_page_size: Optional[int]
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"id": store_id.hex()}
        if root_hash is not None:
            request["root_hash"] = root_hash.hex()
        if page is not None:
            request["page"] = page
        if max_page_size is not None:
            request["max_page_size"] = max_page_size
        response = await self.fetch("get_keys_values", request)
        return response

    async def get_keys(
        self, store_id: bytes32, root_hash: Optional[bytes32], page: Optional[int], max_page_size: Optional[int]
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"id": store_id.hex()}
        if root_hash is not None:
            request["root_hash"] = root_hash.hex()
        if page is not None:
            request["page"] = page
        if max_page_size is not None:
            request["max_page_size"] = max_page_size
        response = await self.fetch("get_keys", request)
        return response

    async def get_ancestors(self, store_id: bytes32, hash: bytes32) -> dict[str, Any]:
        response = await self.fetch("get_ancestors", {"id": store_id.hex(), "hash": hash})
        return response

    async def get_root(self, store_id: bytes32) -> dict[str, Any]:
        response = await self.fetch("get_root", {"id": store_id.hex()})
        return response

    async def get_local_root(self, store_id: bytes32) -> dict[str, Any]:
        response = await self.fetch("get_local_root", {"id": store_id.hex()})
        return response

    async def get_roots(self, store_ids: list[bytes32]) -> dict[str, Any]:
        response = await self.fetch("get_roots", {"ids": store_ids})
        return response

    async def subscribe(self, store_id: bytes32, urls: list[str]) -> dict[str, Any]:
        response = await self.fetch("subscribe", {"id": store_id.hex(), "urls": urls})
        return response

    async def remove_subscriptions(self, store_id: bytes32, urls: list[str]) -> dict[str, Any]:
        response = await self.fetch("remove_subscriptions", {"id": store_id.hex(), "urls": urls})
        return response

    async def unsubscribe(self, store_id: bytes32, retain: bool) -> dict[str, Any]:
        response = await self.fetch("unsubscribe", {"id": store_id.hex(), "retain": retain})
        return response

    async def add_missing_files(
        self, store_ids: Optional[list[bytes32]], overwrite: Optional[bool], foldername: Optional[Path]
    ) -> dict[str, Any]:
        request: dict[str, Any] = {}
        if store_ids is not None:
            request["ids"] = [store_id.hex() for store_id in store_ids]
        if overwrite is not None:
            request["overwrite"] = overwrite
        if foldername is not None:
            request["foldername"] = str(foldername)
        response = await self.fetch("add_missing_files", request)
        return response

    async def get_kv_diff(
        self, store_id: bytes32, hash_1: bytes32, hash_2: bytes32, page: Optional[int], max_page_size: Optional[int]
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"id": store_id.hex(), "hash_1": hash_1.hex(), "hash_2": hash_2.hex()}
        if page is not None:
            request["page"] = page
        if max_page_size is not None:
            request["max_page_size"] = max_page_size
        response = await self.fetch("get_kv_diff", request)
        return response

    async def get_root_history(self, store_id: bytes32) -> dict[str, Any]:
        response = await self.fetch("get_root_history", {"id": store_id.hex()})
        return response

    async def add_mirror(
        self, store_id: bytes32, urls: list[str], amount: int, fee: Optional[uint64]
    ) -> dict[str, Any]:
        response = await self.fetch("add_mirror", {"id": store_id.hex(), "urls": urls, "amount": amount, "fee": fee})
        return response

    async def delete_mirror(self, coin_id: bytes32, fee: Optional[uint64]) -> dict[str, Any]:
        response = await self.fetch("delete_mirror", {"coin_id": coin_id.hex(), "fee": fee})
        return response

    async def get_mirrors(self, store_id: bytes32) -> dict[str, Any]:
        response = await self.fetch("get_mirrors", {"id": store_id.hex()})
        return response

    async def get_subscriptions(self) -> dict[str, Any]:
        response = await self.fetch("subscriptions", {})
        return response

    async def get_owned_stores(self) -> dict[str, Any]:
        response = await self.fetch("get_owned_stores", {})
        return response

    async def get_sync_status(self, store_id: bytes32) -> dict[str, Any]:
        response = await self.fetch("get_sync_status", {"id": store_id.hex()})
        return response

    async def check_plugins(self) -> dict[str, Any]:
        response = await self.fetch("check_plugins", {})
        return response

    async def clear_pending_roots(self, store_id: bytes32) -> dict[str, Any]:
        request = ClearPendingRootsRequest(store_id=store_id)
        response = await self.fetch("clear_pending_roots", request.marshal())
        return response

    async def get_proof(self, store_id: bytes32, keys: list[bytes]) -> dict[str, Any]:
        request: dict[str, Any] = {"store_id": store_id.hex(), "keys": [key.hex() for key in keys]}
        response = await self.fetch("get_proof", request)
        return response

    async def verify_proof(self, proof: dict[str, Any]) -> dict[str, Any]:
        response = await self.fetch("verify_proof", proof)
        return response
