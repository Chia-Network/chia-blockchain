from __future__ import annotations

import contextlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from chia.cmds.cmds_util import get_any_service_client
from chia.cmds.units import units
from chia.rpc.data_layer_rpc_client import DataLayerRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint64


@contextlib.asynccontextmanager
async def get_client(
    rpc_port: Optional[int], fingerprint: Optional[int] = None, root_path: Optional[Path] = None
) -> AsyncIterator[Tuple[DataLayerRpcClient, Dict[str, Any]]]:
    async with get_any_service_client(
        client_type=DataLayerRpcClient,
        rpc_port=rpc_port,
        root_path=root_path,
    ) as (client, _):
        if fingerprint is not None:
            await client.wallet_log_in(fingerprint=fingerprint)
        yield client, _


async def wallet_log_in_cmd(
    rpc_port: Optional[int],
    fingerprint: int,
    root_path: Optional[Path] = None,
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        pass


async def create_data_store_cmd(
    rpc_port: Optional[int],
    fee: Optional[str],
    verbose: bool,
    fingerprint: Optional[int],
) -> None:
    final_fee = None if fee is None else uint64(int(Decimal(fee) * units["chia"]))
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.create_data_store(fee=final_fee, verbose=verbose)
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_value_cmd(
    rpc_port: Optional[int],
    store_id: str,
    key: str,
    root_hash: Optional[str],
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    key_bytes = hexstr_to_bytes(key)
    root_hash_bytes = None if root_hash is None else bytes32.from_hexstr(root_hash)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_value(store_id=store_id_bytes, key=key_bytes, root_hash=root_hash_bytes)
        print(json.dumps(res, indent=4, sort_keys=True))


async def update_data_store_cmd(
    rpc_port: Optional[int],
    store_id: str,
    changelist: List[Dict[str, str]],
    fee: Optional[str],
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    final_fee = None if fee is None else uint64(int(Decimal(fee) * units["chia"]))
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.update_data_store(store_id=store_id_bytes, changelist=changelist, fee=final_fee)
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_keys_cmd(
    rpc_port: Optional[int],
    store_id: str,
    root_hash: Optional[str],
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    root_hash_bytes = None if root_hash is None else bytes32.from_hexstr(root_hash)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_keys(store_id=store_id_bytes, root_hash=root_hash_bytes)
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_keys_values_cmd(
    rpc_port: Optional[int],
    store_id: str,
    root_hash: Optional[str],
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    root_hash_bytes = None if root_hash is None else bytes32.from_hexstr(root_hash)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_keys_values(store_id=store_id_bytes, root_hash=root_hash_bytes)
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_root_cmd(
    rpc_port: Optional[int],
    store_id: str,
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_root(store_id=store_id_bytes)
        print(json.dumps(res, indent=4, sort_keys=True))


async def subscribe_cmd(
    rpc_port: Optional[int],
    store_id: str,
    urls: List[str],
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.subscribe(store_id=store_id_bytes, urls=urls)
        print(json.dumps(res, indent=4, sort_keys=True))


async def unsubscribe_cmd(
    rpc_port: Optional[int],
    store_id: str,
    fingerprint: Optional[int],
    retain: bool,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.unsubscribe(store_id=store_id_bytes, retain=retain)
        print(json.dumps(res, indent=4, sort_keys=True))


async def remove_subscriptions_cmd(
    rpc_port: Optional[int],
    store_id: str,
    urls: List[str],
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.remove_subscriptions(store_id=store_id_bytes, urls=urls)
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_kv_diff_cmd(
    rpc_port: Optional[int],
    store_id: str,
    hash_1: str,
    hash_2: str,
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    hash_1_bytes = bytes32.from_hexstr(hash_1)
    hash_2_bytes = bytes32.from_hexstr(hash_2)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_kv_diff(store_id=store_id_bytes, hash_1=hash_1_bytes, hash_2=hash_2_bytes)
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_root_history_cmd(
    rpc_port: Optional[int],
    store_id: str,
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_root_history(store_id=store_id_bytes)
        print(json.dumps(res, indent=4, sort_keys=True))


async def add_missing_files_cmd(
    rpc_port: Optional[int],
    ids: Optional[List[str]],
    overwrite: bool,
    foldername: Optional[Path],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.add_missing_files(
            store_ids=(None if ids is None else [bytes32.from_hexstr(id) for id in ids]),
            overwrite=overwrite,
            foldername=foldername,
        )
        print(json.dumps(res, indent=4, sort_keys=True))


async def add_mirror_cmd(
    rpc_port: Optional[int],
    store_id: str,
    urls: List[str],
    amount: int,
    fee: Optional[str],
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    final_fee = None if fee is None else uint64(int(Decimal(fee) * units["chia"]))
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.add_mirror(
            store_id=store_id_bytes,
            urls=urls,
            amount=amount,
            fee=final_fee,
        )
        print(json.dumps(res, indent=4, sort_keys=True))


async def delete_mirror_cmd(
    rpc_port: Optional[int],
    coin_id: str,
    fee: Optional[str],
    fingerprint: Optional[int],
) -> None:
    coin_id_bytes = bytes32.from_hexstr(coin_id)
    final_fee = None if fee is None else uint64(int(Decimal(fee) * units["chia"]))
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.delete_mirror(
            coin_id=coin_id_bytes,
            fee=final_fee,
        )
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_mirrors_cmd(
    rpc_port: Optional[int],
    store_id: str,
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_mirrors(store_id=store_id_bytes)
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_subscriptions_cmd(
    rpc_port: Optional[int],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_subscriptions()
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_owned_stores_cmd(
    rpc_port: Optional[int],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_owned_stores()
        print(json.dumps(res, indent=4, sort_keys=True))


async def get_sync_status_cmd(
    rpc_port: Optional[int],
    store_id: str,
    fingerprint: Optional[int],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_sync_status(store_id=store_id_bytes)
        print(json.dumps(res, indent=4, sort_keys=True))


async def check_plugins_cmd(rpc_port: Optional[int]) -> None:
    async with get_client(rpc_port=rpc_port) as (client, _):
        res = await client.check_plugins()
        print(json.dumps(res, indent=4, sort_keys=True))


async def clear_pending_roots(
    store_id: bytes32,
    rpc_port: Optional[int],
    root_path: Optional[Path] = None,
    fingerprint: Optional[int] = None,
) -> Dict[str, Any]:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        result = await client.clear_pending_roots(store_id=store_id)
        print(json.dumps(result, indent=4, sort_keys=True))

    return result
