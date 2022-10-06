from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional, Tuple, cast

import aiohttp

from chia.cmds.units import units
from chia.rpc.data_layer_rpc_client import DataLayerRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint64

# TODO: there seems to be a large amount of repetition in these to dedupe


@asynccontextmanager
async def get_client(rpc_port: Optional[int]) -> AsyncIterator[Tuple[DataLayerRpcClient, int]]:
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml", fill_missing_services=True)
    self_hostname = config["self_hostname"]

    if rpc_port is None:
        rpc_port = cast(int, config["data_layer"]["rpc_port"])

    client = await DataLayerRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)
    try:
        yield client, rpc_port
    finally:
        client.close()
        await client.await_closed()


async def create_data_store_cmd(rpc_port: Optional[int], fee: Optional[str]) -> None:
    final_fee = None
    if fee is not None:
        final_fee = uint64(int(Decimal(fee) * units["chia"]))
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.create_data_store(fee=final_fee)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")
    return


async def get_value_cmd(rpc_port: Optional[int], store_id: str, key: str, root_hash: Optional[str]) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    key_bytes = hexstr_to_bytes(key)
    root_hash_bytes = None if root_hash is None else bytes32.from_hexstr(root_hash)

    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_value(store_id=store_id_bytes, key=key_bytes, root_hash=root_hash_bytes)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")
    return


async def update_data_store_cmd(
    rpc_port: Optional[int],
    store_id: str,
    changelist: List[Dict[str, str]],
    fee: Optional[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    final_fee = None
    if fee is not None:
        final_fee = uint64(int(Decimal(fee) * units["chia"]))
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.update_data_store(store_id=store_id_bytes, changelist=changelist, fee=final_fee)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")
    return


async def get_keys_cmd(
    rpc_port: Optional[int],
    store_id: str,
    root_hash: Optional[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    root_hash_bytes = None if root_hash is None else bytes32.from_hexstr(root_hash)

    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_keys(store_id=store_id_bytes, root_hash=root_hash_bytes)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")
    return


async def get_keys_values_cmd(
    rpc_port: Optional[int],
    store_id: str,
    root_hash: Optional[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    root_hash_bytes = None if root_hash is None else bytes32.from_hexstr(root_hash)

    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_keys_values(store_id=store_id_bytes, root_hash=root_hash_bytes)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")
    return


async def get_root_cmd(
    rpc_port: Optional[int],
    store_id: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_root(store_id=store_id_bytes)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")
    return


async def subscribe_cmd(
    rpc_port: Optional[int],
    store_id: str,
    urls: List[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.subscribe(store_id=store_id_bytes, urls=urls)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def unsubscribe_cmd(
    rpc_port: Optional[int],
    store_id: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.unsubscribe(store_id=store_id_bytes)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def remove_subscriptions_cmd(
    rpc_port: Optional[int],
    store_id: str,
    urls: List[str],
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.remove_subscriptions(store_id=store_id_bytes, urls=urls)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def get_kv_diff_cmd(
    rpc_port: Optional[int],
    store_id: str,
    hash_1: str,
    hash_2: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    hash_1_bytes = bytes32.from_hexstr(hash_1)
    hash_2_bytes = bytes32.from_hexstr(hash_2)

    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_kv_diff(store_id=store_id_bytes, hash_1=hash_1_bytes, hash_2=hash_2_bytes)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def get_root_history_cmd(
    rpc_port: Optional[int],
    store_id: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_root_history(store_id=store_id_bytes)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def add_missing_files_cmd(
    rpc_port: Optional[int], ids: Optional[List[str]], overwrite: bool, foldername: Optional[Path]
) -> None:
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.add_missing_files(
                store_ids=(None if ids is None else [bytes32.from_hexstr(id) for id in ids]),
                overwrite=overwrite,
                foldername=foldername,
            )
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def add_mirror_cmd(
    rpc_port: Optional[int], store_id: str, urls: List[str], amount: int, fee: Optional[str]
) -> None:
    try:
        store_id_bytes = bytes32.from_hexstr(store_id)
        final_fee = None
        if fee is not None:
            final_fee = uint64(int(Decimal(fee) * units["chia"]))
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.add_mirror(
                store_id=store_id_bytes,
                urls=urls,
                amount=amount,
                fee=final_fee,
            )
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def delete_mirror_cmd(rpc_port: Optional[int], coin_id: str, fee: Optional[str]) -> None:
    try:
        coin_id_bytes = bytes32.from_hexstr(coin_id)
        final_fee = None
        if fee is not None:
            final_fee = uint64(int(Decimal(fee) * units["chia"]))
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.delete_mirror(
                coin_id=coin_id_bytes,
                fee=final_fee,
            )
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def get_mirrors_cmd(rpc_port: Optional[int], store_id: str) -> None:
    try:
        store_id_bytes = bytes32.from_hexstr(store_id)
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_mirrors(store_id=store_id_bytes)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def get_subscriptions_cmd(rpc_port: Optional[int]) -> None:
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_subscriptions()
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")


async def get_owned_stores_cmd(rpc_port: Optional[int]) -> None:
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_owned_stores()
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")
