import json
from typing import Any, Optional, Dict, Callable

import aiohttp

from chia.rpc.data_layer_rpc_client import DataLayerRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint32, uint16


async def create_kv_store_cmd(fingerprint: int, rpc_port: int) -> Any:
    # TODO: nice cli error handling
    response = None
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if rpc_port is None:
            rpc_port = config["data_layer"]["rpc_port"]
        client = await DataLayerRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)
        response = await client.create_kv_store()
    except Exception as e:
        print(f"Exception from 'data service' {e}")
    client.close()
    await client.await_closed()
    return response


async def get_value_cmd(tree_id: str, key: str, fingerprint: int, rpc_port) -> Optional[Dict[str, Any]]:
    # TODO: nice cli error handling
    tree_id_bytes = bytes32(hexstr_to_bytes(tree_id))
    key_bytes = hexstr_to_bytes(key)
    response = None
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if rpc_port is None:
            rpc_port = config["data_layer"]["rpc_port"]
        client = await DataLayerRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)
        response = await client.get_value(tree_id=tree_id_bytes, key=key_bytes)
    except Exception as e:
        print(f"Exception from 'data service' {e}")
    client.close()
    await client.await_closed()
    return response


async def update_kv_store_cmd(
    tree_id: str, changelist: Dict, fingerprint: int, rpc_port: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    # TODO: nice cli error handling
    tree_id_bytes = bytes32(hexstr_to_bytes(tree_id))
    response = None
    try:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if rpc_port is None:
            rpc_port = config["data_layer"]["rpc_port"]
        client = await DataLayerRpcClient.create(self_hostname, uint16(rpc_port), DEFAULT_ROOT_PATH, config)
        response = await client.update_kv_store(tree_id_bytes, changelist)
    except Exception as e:
        print(f"Exception from 'data service' {e}")
    client.close()
    await client.await_closed()
    return response
