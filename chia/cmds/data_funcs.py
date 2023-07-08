from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from chia.cmds.cmds_util import get_any_service_client
from chia.rpc.data_layer_rpc_client import DataLayerRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint64


async def create_data_store_cmd(rpc_port: Optional[int], fee: Optional[uint64]) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.create_data_store(fee=fee)
        print(res)


async def get_value_cmd(rpc_port: Optional[int], store_id: bytes32, key: str, root_hash: Optional[bytes32]) -> None:
    key_bytes = hexstr_to_bytes(key)
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_value(store_id=store_id, key=key_bytes, root_hash=root_hash)
        print(res)


async def update_data_store_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    changelist: List[Dict[str, str]],
    fee: Optional[uint64],
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.update_data_store(store_id=store_id, changelist=changelist, fee=fee)
        print(res)


async def get_keys_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    root_hash: Optional[bytes32],
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_keys(store_id=store_id, root_hash=root_hash)
        print(res)


async def get_keys_values_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    root_hash: Optional[bytes32],
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_keys_values(store_id=store_id, root_hash=root_hash)
        print(res)


async def get_root_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_root(store_id=store_id)
        print(res)


async def subscribe_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    urls: List[str],
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.subscribe(store_id=store_id, urls=urls)
        print(res)


async def unsubscribe_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.unsubscribe(store_id=store_id)
        print(res)


async def remove_subscriptions_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    urls: List[str],
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.remove_subscriptions(store_id=store_id, urls=urls)
        print(res)


async def get_kv_diff_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    hash_1: bytes32,
    hash_2: bytes32,
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_kv_diff(store_id=store_id, hash_1=hash_1, hash_2=hash_2)
        print(res)


async def get_root_history_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_root_history(store_id=store_id)
        print(res)


async def add_missing_files_cmd(
    rpc_port: Optional[int], ids: Optional[List[str]], overwrite: bool, foldername: Optional[Path]
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.add_missing_files(
            store_ids=(None if ids is None else [bytes32.from_hexstr(id) for id in ids]),
            overwrite=overwrite,
            foldername=foldername,
        )
        print(res)


async def add_mirror_cmd(
    rpc_port: Optional[int], store_id: bytes32, urls: List[str], amount: int, fee: Optional[uint64]
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.add_mirror(
            store_id=store_id,
            urls=urls,
            amount=amount,
            fee=fee,
        )
        print(res)


async def delete_mirror_cmd(rpc_port: Optional[int], coin_id: bytes32, fee: Optional[uint64]) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.delete_mirror(
            coin_id=coin_id,
            fee=fee,
        )
        print(res)


async def get_mirrors_cmd(rpc_port: Optional[int], store_id: bytes32) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_mirrors(store_id=store_id)
        print(res)


async def get_subscriptions_cmd(rpc_port: Optional[int]) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_subscriptions()
        print(res)


async def get_owned_stores_cmd(rpc_port: Optional[int]) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_owned_stores()
        print(res)


async def get_sync_status_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.get_sync_status(store_id=store_id)
        print(res)


async def check_plugins_cmd(rpc_port: Optional[int]) -> None:
    async with get_any_service_client(DataLayerRpcClient, rpc_port) as (client, _):
        res = await client.check_plugins()
        print(json.dumps(res, indent=4, sort_keys=True))


async def clear_pending_roots(
    store_id: bytes32,
    rpc_port: Optional[int],
    root_path: Path = DEFAULT_ROOT_PATH,
) -> Dict[str, Any]:
    async with get_any_service_client(DataLayerRpcClient, rpc_port, root_path=root_path) as (client, _):
        result = await client.clear_pending_roots(store_id=store_id)
        print(json.dumps(result, indent=4, sort_keys=True))

    return result
