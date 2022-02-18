from decimal import Decimal
from typing import Optional, Tuple, Dict, Type
from types import TracebackType

import aiohttp

from chia.cmds.units import units
from chia.rpc.data_layer_rpc_client import DataLayerRpcClient
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16, uint64


# TODO: there seems to be a large amount of repetition in these to dedupe


class get_client:
    _port: Optional[int]
    _client: Optional[DataLayerRpcClient] = None

    def __init__(self, rpc_port: Optional[int]):
        self._port = rpc_port

    async def __aenter__(self) -> Tuple[DataLayerRpcClient, int]:
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        self_hostname = config["self_hostname"]
        if self._port is None:
            self._port = config["data_layer"]["rpc_port"]
        self._client = await DataLayerRpcClient.create(self_hostname, uint16(self._port), DEFAULT_ROOT_PATH, config)
        assert self._client is not None
        return self._client, int(self._port)

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if self._client is None:
            return
        self._client.close()
        await self._client.await_closed()


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


async def get_value_cmd(rpc_port: Optional[int], store_id: str, key: str) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    key_bytes = hexstr_to_bytes(key)
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_value(store_id=store_id_bytes, key=key_bytes)
            print(res)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")
    return


async def update_data_store_cmd(
    rpc_port: Optional[int],
    store_id: str,
    changelist: Dict[str, str],
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


async def get_keys_values_cmd(
    rpc_port: Optional[int],
    store_id: str,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            res = await client.get_keys_values(store_id=store_id_bytes)
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
    ip: str,
    port: int,
) -> None:
    store_id_bytes = bytes32.from_hexstr(store_id)
    try:
        async with get_client(rpc_port) as (client, rpc_port):
            await client.subscribe(store_id=store_id_bytes, ip=ip, port=uint16(port))
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
            await client.unsubscribe(store_id=store_id_bytes)
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
            await client.get_kv_diff(store_id=store_id_bytes, hash_1=hash_1_bytes, hash_2=hash_2_bytes)
    except aiohttp.ClientConnectorError:
        print(f"Connection error. Check if data is running at {rpc_port}")
    except Exception as e:
        print(f"Exception from 'data': {e}")
