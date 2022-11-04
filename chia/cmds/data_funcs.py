from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from chia.cmds.cmds_util import get_any_service_client
from chia.cmds.units import units
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint64


async def create_data_store_cmd(rpc_port: Optional[int], fee: Optional[str]) -> None:
    final_fee = None if fee is None else uint64(int(Decimal(fee) * units["chia"]))
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.create_data_store(fee=final_fee)
            print(res)


async def get_value_cmd(rpc_port: Optional[int], store_id: str, key: str, root_hash: Optional[str]) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    key_bytes = hexstr_to_bytes(key)
    root_hash_bytes = None if root_hash is None else bytes32.from_hexstr(root_hash)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_value(store_id=store_id_bytes, key=key_bytes, root_hash=root_hash_bytes)
            print(res)


async def update_data_store_cmd(
    rpc_port: Optional[int],
    store_id: str,
    changelist: List[Dict[str, str]],
    fee: Optional[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    final_fee = None if fee is None else uint64(int(Decimal(fee) * units["chia"]))
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.update_data_store(store_id=store_id_bytes, changelist=changelist, fee=final_fee)
            print(res)


async def get_keys_cmd(
    rpc_port: Optional[int],
    store_id: str,
    root_hash: Optional[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    root_hash_bytes = None if root_hash is None else bytes32.from_hexstr(root_hash)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_keys(store_id=store_id_bytes, root_hash=root_hash_bytes)
            print(res)


async def get_keys_values_cmd(
    rpc_port: Optional[int],
    store_id: str,
    root_hash: Optional[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    root_hash_bytes = None if root_hash is None else bytes32.from_hexstr(root_hash)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_keys_values(store_id=store_id_bytes, root_hash=root_hash_bytes)
            print(res)


async def get_root_cmd(
    rpc_port: Optional[int],
    store_id: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_root(store_id=store_id_bytes)
            print(res)


async def subscribe_cmd(
    rpc_port: Optional[int],
    store_id: str,
    urls: List[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.subscribe(store_id=store_id_bytes, urls=urls)
            print(res)


async def unsubscribe_cmd(
    rpc_port: Optional[int],
    store_id: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.unsubscribe(store_id=store_id_bytes)
            print(res)


async def remove_subscriptions_cmd(
    rpc_port: Optional[int],
    store_id: str,
    urls: List[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.remove_subscriptions(store_id=store_id_bytes, urls=urls)
            print(res)


async def get_kv_diff_cmd(
    rpc_port: Optional[int],
    store_id: str,
    hash_1: str,
    hash_2: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    hash_1_bytes = bytes32.from_hexstr(hash_1)
    hash_2_bytes = bytes32.from_hexstr(hash_2)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_kv_diff(store_id=store_id_bytes, hash_1=hash_1_bytes, hash_2=hash_2_bytes)
            print(res)


async def get_root_history_cmd(
    rpc_port: Optional[int],
    store_id: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_root_history(store_id=store_id_bytes)
            print(res)


async def add_missing_files_cmd(
    rpc_port: Optional[int], ids: Optional[List[str]], overwrite: bool, foldername: Optional[Path]
) -> None:
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.add_missing_files(
                store_ids=(None if ids is None else [bytes32.from_hexstr(id) for id in ids]),
                overwrite=overwrite,
                foldername=foldername,
            )
            print(res)


async def add_mirror_cmd(
    rpc_port: Optional[int], store_id: str, urls: List[str], amount: int, fee: Optional[str]
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    final_fee = None if fee is None else uint64(int(Decimal(fee) * units["chia"]))
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.add_mirror(
                store_id=store_id_bytes,
                urls=urls,
                amount=amount,
                fee=final_fee,
            )
            print(res)


async def delete_mirror_cmd(rpc_port: Optional[int], coin_id: str, fee: Optional[str]) -> None:
    coin_id_bytes = bytes32.from_hexstr(coin_id)
    final_fee = None if fee is None else uint64(int(Decimal(fee) * units["chia"]))
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.delete_mirror(
                coin_id=coin_id_bytes,
                fee=final_fee,
            )
            print(res)


async def get_mirrors_cmd(rpc_port: Optional[int], store_id: str) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_mirrors(store_id=store_id_bytes)
            print(res)


async def get_subscriptions_cmd(rpc_port: Optional[int]) -> None:
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_subscriptions()
            print(res)


async def get_owned_stores_cmd(rpc_port: Optional[int]) -> None:
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_owned_stores()
            print(res)


async def get_sync_status_cmd(
    rpc_port: Optional[int],
    store_id: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_any_service_client("data_layer", rpc_port) as (client, config, _):
        if client is not None:
            res = await client.get_sync_status(store_id=store_id_bytes)
            print(res)
