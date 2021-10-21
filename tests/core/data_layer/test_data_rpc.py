from typing import List, Dict
import pytest

# flake8: noqa: F401
import aiosqlite
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_store import DataStore
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.db_wrapper import DBWrapper
from chia.util.hash import std_hash

from tests.core.data_layer.util import ChiaRoot


@pytest.mark.asyncio
async def test_create_insert_get(chia_root: ChiaRoot) -> None:
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    data_layer = DataLayer(config["data_layer"], root_path=root, consensus_constants=DEFAULT_CONSTANTS)
    connection = await aiosqlite.connect(data_layer.db_path)
    data_layer.connection = connection
    data_layer.db_wrapper = DBWrapper(data_layer.connection)
    data_layer.data_store = await DataStore.create(data_layer.db_wrapper)
    data_layer.initialized = True
    rpc_api = DataLayerRpcApi(data_layer)
    key = b"a"
    value = b"\x00\x01"
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
    res = await rpc_api.create_kv_store()
    store_id = bytes32(hexstr_to_bytes(res["id"]))
    await rpc_api.update_kv_store({"id": store_id.hex(), "changelist": changelist})
    res = await rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
    assert hexstr_to_bytes(res["data"]) == value
    changelist = [{"action": "delete", "key": key.hex()}]
    await rpc_api.update_kv_store({"id": store_id.hex(), "changelist": changelist})
    with pytest.raises(Exception):
        val = await rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
    await connection.close()


@pytest.mark.asyncio
async def test_create_double_insert(chia_root: ChiaRoot) -> None:
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    data_layer = DataLayer(config["data_layer"], root_path=root, consensus_constants=DEFAULT_CONSTANTS)
    connection = await aiosqlite.connect(data_layer.db_path)
    data_layer.connection = connection
    data_layer.db_wrapper = DBWrapper(data_layer.connection)
    data_layer.data_store = await DataStore.create(data_layer.db_wrapper)
    data_layer.initialized = True
    rpc_api = DataLayerRpcApi(data_layer)
    key1 = b"a"
    value1 = b"\x01\x02"
    key2 = b"b"
    value2 = b"\x01\x23"
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.hex(), "value": value1.hex()}]
    res = await rpc_api.create_kv_store()
    store_id = bytes32(hexstr_to_bytes(res["id"]))
    await rpc_api.update_kv_store({"id": store_id.hex(), "changelist": changelist})
    res = await rpc_api.get_value({"id": store_id.hex(), "key": key1.hex()})
    assert hexstr_to_bytes(res["data"]) == value1

    changelist = [{"action": "insert", "key": key2.hex(), "value": value2.hex()}]
    await rpc_api.update_kv_store({"id": store_id.hex(), "changelist": changelist})
    res = await rpc_api.get_value({"id": store_id.hex(), "key": key2.hex()})
    assert hexstr_to_bytes(res["data"]) == value2

    changelist = [{"action": "delete", "key": key1.hex()}]
    await rpc_api.update_kv_store({"id": store_id.hex(), "changelist": changelist})
    with pytest.raises(Exception):
        val = await rpc_api.get_value({"id": store_id.hex(), "key": key1.hex()})
    await connection.close()


@pytest.mark.asyncio
async def test_get_pairs(chia_root: ChiaRoot) -> None:
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    data_layer = DataLayer(config["data_layer"], root_path=root, consensus_constants=DEFAULT_CONSTANTS)
    connection = await aiosqlite.connect(data_layer.db_path)
    data_layer.connection = connection
    data_layer.db_wrapper = DBWrapper(data_layer.connection)
    data_layer.data_store = await DataStore.create(data_layer.db_wrapper)
    data_layer.initialized = True
    rpc_api = DataLayerRpcApi(data_layer)
    key1 = b"a"
    value1 = b"\x01\x02"
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.hex(), "value": value1.hex()}]
    key2 = b"b"
    value2 = b"\x03\x02"
    changelist.append({"action": "insert", "key": key2.hex(), "value": value2.hex()})
    key3 = b"c"
    value3 = b"\x04\x05"
    changelist.append({"action": "insert", "key": key3.hex(), "value": value3.hex()})
    key4 = b"d"
    value4 = b"\x06\x03"
    changelist.append({"action": "insert", "key": key4.hex(), "value": value4.hex()})
    key5 = b"e"
    value5 = b"\x07\x01"
    changelist.append({"action": "insert", "key": key5.hex(), "value": value5.hex()})
    res = await rpc_api.create_kv_store()
    tree_id = bytes32(hexstr_to_bytes(res["id"]))
    await rpc_api.update_kv_store({"id": tree_id.hex(), "changelist": changelist})
    val = await rpc_api.get_value({"id": tree_id.hex(), "key": key1.hex()})
    assert hexstr_to_bytes(val["data"]) == value1
    val = await rpc_api.get_value({"id": tree_id.hex(), "key": key1.hex()})
    changelist = [{"action": "delete", "key": key1.hex()}]
    await rpc_api.update_kv_store({"id": tree_id.hex(), "changelist": changelist})
    with pytest.raises(Exception):
        val = await rpc_api.get_value({"id": tree_id.hex(), "key": key1.hex()})
    await connection.close()
