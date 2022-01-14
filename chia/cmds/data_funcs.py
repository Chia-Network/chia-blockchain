import json
from typing import Any, Optional, Tuple, Dict

import aiohttp

from chia.rpc.data_layer_rpc_client import DataLayerRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16


# TODO: there seems to be a large amount of repetition in these to dedupe


async def get_client(rpc_port: Optional[int]) -> Tuple[DataLayerRpcClient, int]:
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    self_hostname = config["self_hostname"]
    if rpc_port is None:
        rpc_port = config["data_layer"]["rpc_port"]
    # TODO: context manager for this and closing etc?
    client = await DataLayerRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)
    return client, rpc_port


async def create_wallet(rpc_port: Optional[int]) -> Optional[Dict[str, Any]]:
    # TODO: nice cli error handling
    try:
        client, rpc_port = await get_client(rpc_port)
        response = await client.create_wallet()
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
        return None
    except Exception as e:
        print(f"Exception from 'data': {e}")
        return None

    client.close()
    await client.await_closed()
    return response


async def create_data_store_cmd(rpc_port: Optional[int], table_string: str) -> Optional[Dict[str, Any]]:
    # TODO: nice cli error handling

    try:
        client, rpc_port = await get_client(rpc_port)
        response = await client.create_data_store()
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
        return None
    except Exception as e:
        print(f"Exception from 'data': {e}")
        return None

    client.close()
    await client.await_closed()
    return response


async def get_value_cmd(rpc_port: Optional[int], tree_id: str, key: str) -> Optional[Dict[str, Any]]:
    # TODO: nice cli error handling

    store_id_bytes = bytes32(hexstr_to_bytes(tree_id))
    key_bytes = hexstr_to_bytes(key)
    try:
        client, rpc_port = await get_client(rpc_port)
        response = await client.get_value(store_id=store_id_bytes, key=key_bytes)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
        return None
    except Exception as e:
        print(f"Exception from 'data': {e}")
        return None

    client.close()
    await client.await_closed()
    return response


async def update_data_store_cmd(
    rpc_port: Optional[int],
    tree_id: str,
    changelist: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    # TODO: nice cli error handling
    store_id_bytes = bytes32(hexstr_to_bytes(tree_id))
    try:
        client, rpc_port = await get_client(rpc_port)
        response = await client.update_data_store(store_id=store_id_bytes, changelist=changelist)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
        return None
    except Exception as e:
        print(f"Exception from 'data': {e}")
        return None

    client.close()
    await client.await_closed()
    return response


async def get_root_cmd(
    rpc_port: Optional[int],
    tree_id: str,
) -> Optional[Dict[str, Any]]:
    # TODO: nice cli error handling
    store_id_bytes = bytes32(hexstr_to_bytes(tree_id))
    try:
        client, rpc_port = await get_client(rpc_port)
        response = await client.get_root(store_id=store_id_bytes)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
        return None
    except Exception as e:
        print(f"Exception from 'data': {e}")
        return None

    client.close()
    await client.await_closed()
    return response
