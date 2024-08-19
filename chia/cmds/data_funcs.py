from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from chia.cmds.cmds_util import get_any_service_client
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
    fee: Optional[uint64],
    verbose: bool,
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.create_data_store(fee=fee, verbose=verbose)
        print(json.dumps(res, indent=2, sort_keys=True))


async def get_value_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    key: str,
    # NOTE: being outside the rpc, this retains the none-means-unspecified semantics
    root_hash: Optional[bytes32],
    fingerprint: Optional[int],
) -> None:
    key_bytes = hexstr_to_bytes(key)
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_value(store_id=store_id, key=key_bytes, root_hash=root_hash)
        print(json.dumps(res, indent=2, sort_keys=True))


async def update_data_store_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    changelist: List[Dict[str, str]],
    fee: Optional[uint64],
    fingerprint: Optional[int],
    submit_on_chain: bool,
    root_path: Optional[Path] = None,
) -> Dict[str, Any]:
    res = dict()
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        res = await client.update_data_store(
            store_id=store_id,
            changelist=changelist,
            fee=fee,
            submit_on_chain=submit_on_chain,
        )
        print(json.dumps(res, indent=2, sort_keys=True))

    return res


async def update_multiple_stores_cmd(
    rpc_port: Optional[int],
    store_updates: List[Dict[str, str]],
    fee: Optional[uint64],
    fingerprint: Optional[int],
    submit_on_chain: bool,
    root_path: Optional[Path] = None,
) -> Dict[str, Any]:
    res = dict()

    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        res = await client.update_multiple_stores(
            store_updates=store_updates,
            fee=fee,
            submit_on_chain=submit_on_chain,
        )
        print(json.dumps(res, indent=2, sort_keys=True))

    return res


async def submit_pending_root_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    fee: Optional[uint64],
    fingerprint: Optional[int],
    root_path: Optional[Path] = None,
) -> Dict[str, Any]:
    res = dict()
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        res = await client.submit_pending_root(
            store_id=store_id,
            fee=fee,
        )
        print(json.dumps(res, indent=2, sort_keys=True))

    return res


async def submit_all_pending_roots_cmd(
    rpc_port: Optional[int],
    fee: Optional[uint64],
    fingerprint: Optional[int],
    root_path: Optional[Path] = None,
) -> Dict[str, Any]:
    res = dict()
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        res = await client.submit_all_pending_roots(fee=fee)
        print(json.dumps(res, indent=2, sort_keys=True))

    return res


async def get_keys_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    # NOTE: being outside the rpc, this retains the none-means-unspecified semantics
    root_hash: Optional[bytes32],
    fingerprint: Optional[int],
    page: Optional[int],
    max_page_size: Optional[int],
    root_path: Optional[Path] = None,
) -> Dict[str, Any]:
    res = dict()
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        res = await client.get_keys(store_id=store_id, root_hash=root_hash, page=page, max_page_size=max_page_size)
        print(json.dumps(res, indent=2, sort_keys=True))

    return res


async def get_keys_values_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    # NOTE: being outside the rpc, this retains the none-means-unspecified semantics
    root_hash: Optional[bytes32],
    fingerprint: Optional[int],
    page: Optional[int],
    max_page_size: Optional[int],
    root_path: Optional[Path] = None,
) -> Dict[str, Any]:
    res = dict()
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        res = await client.get_keys_values(
            store_id=store_id, root_hash=root_hash, page=page, max_page_size=max_page_size
        )
        print(json.dumps(res, indent=2, sort_keys=True))

    return res


async def get_root_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_root(store_id=store_id)
        print(json.dumps(res, indent=2, sort_keys=True))


async def subscribe_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    urls: List[str],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.subscribe(store_id=store_id, urls=urls)
        print(json.dumps(res, indent=2, sort_keys=True))


async def unsubscribe_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    fingerprint: Optional[int],
    retain: bool,
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.unsubscribe(store_id=store_id, retain=retain)
        print(json.dumps(res, indent=2, sort_keys=True))


async def remove_subscriptions_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    urls: List[str],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.remove_subscriptions(store_id=store_id, urls=urls)
        print(json.dumps(res, indent=2, sort_keys=True))


async def get_kv_diff_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    hash_1: bytes32,
    hash_2: bytes32,
    fingerprint: Optional[int],
    page: Optional[int],
    max_page_size: Optional[int],
    root_path: Optional[Path] = None,
) -> Dict[str, Any]:
    res = dict()
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        res = await client.get_kv_diff(
            store_id=store_id, hash_1=hash_1, hash_2=hash_2, page=page, max_page_size=max_page_size
        )
        print(json.dumps(res, indent=2, sort_keys=True))

    return res


async def get_root_history_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_root_history(store_id=store_id)
        print(json.dumps(res, indent=2, sort_keys=True))


async def add_missing_files_cmd(
    rpc_port: Optional[int],
    ids: Optional[List[bytes32]],
    overwrite: bool,
    foldername: Optional[Path],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.add_missing_files(
            store_ids=ids,
            overwrite=overwrite,
            foldername=foldername,
        )
        print(json.dumps(res, indent=2, sort_keys=True))


async def add_mirror_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    urls: List[str],
    amount: int,
    fee: Optional[uint64],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.add_mirror(
            store_id=store_id,
            urls=urls,
            amount=amount,
            fee=fee,
        )
        print(json.dumps(res, indent=2, sort_keys=True))


async def delete_mirror_cmd(
    rpc_port: Optional[int],
    coin_id: bytes32,
    fee: Optional[uint64],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.delete_mirror(
            coin_id=coin_id,
            fee=fee,
        )
        print(json.dumps(res, indent=2, sort_keys=True))


async def get_mirrors_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_mirrors(store_id=store_id)
        print(json.dumps(res, indent=2, sort_keys=True))


async def get_subscriptions_cmd(
    rpc_port: Optional[int],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_subscriptions()
        print(json.dumps(res, indent=2, sort_keys=True))


async def get_owned_stores_cmd(
    rpc_port: Optional[int],
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_owned_stores()
        print(json.dumps(res, indent=2, sort_keys=True))


async def get_sync_status_cmd(
    rpc_port: Optional[int],
    store_id: bytes32,
    fingerprint: Optional[int],
) -> None:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint) as (client, _):
        res = await client.get_sync_status(store_id=store_id)
        print(json.dumps(res, indent=2, sort_keys=True))


async def check_plugins_cmd(rpc_port: Optional[int]) -> None:
    async with get_client(rpc_port=rpc_port) as (client, _):
        res = await client.check_plugins()
        print(json.dumps(res, indent=2, sort_keys=True))


async def clear_pending_roots(
    store_id: bytes32,
    rpc_port: Optional[int],
    root_path: Optional[Path] = None,
    fingerprint: Optional[int] = None,
) -> Dict[str, Any]:
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        result = await client.clear_pending_roots(store_id=store_id)
        print(json.dumps(result, indent=2, sort_keys=True))

    return result


async def get_proof_cmd(
    store_id: bytes32,
    key_strings: List[str],
    rpc_port: Optional[int],
    root_path: Optional[Path] = None,
    fingerprint: Optional[int] = None,
) -> Dict[str, Any]:
    result = dict()
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        result = await client.get_proof(store_id=store_id, keys=[hexstr_to_bytes(key) for key in key_strings])
        print(json.dumps(result, indent=2, sort_keys=True))

    return result


async def verify_proof_cmd(
    proof: Dict[str, Any],
    rpc_port: Optional[int],
    root_path: Optional[Path] = None,
    fingerprint: Optional[int] = None,
) -> Dict[str, Any]:
    result = dict()
    async with get_client(rpc_port=rpc_port, fingerprint=fingerprint, root_path=root_path) as (client, _):
        result = await client.verify_proof(proof=proof)
        print(json.dumps(result, indent=2, sort_keys=True))

    return result
