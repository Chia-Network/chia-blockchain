from typing import List, Dict
import pytest

# flake8: noqa: F401
import aiosqlite
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_store import DataStore
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.types.blockchain_format.program import Program
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
    key = std_hash(b"a")
    value = std_hash(Program.to([1, 2]))
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key, "value": value}]
    res = await rpc_api.create_kv_store()
    store_id = res["id"]
    await rpc_api.update_kv_store({"id": store_id, "changelist": changelist})
    res = await rpc_api.get_value({"id": store_id, "key": key})
    assert res["data"] == value
    changelist = [{"action": "delete", "key": key}]
    await rpc_api.update_kv_store({"id": store_id, "changelist": changelist})
    with pytest.raises(Exception):
        val = await rpc_api.get_value({"id": store_id, "key": key.as_bin()})
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
    key1 = std_hash(b"a")
    value1 = std_hash(Program.to([1, 2]))
    key2 = std_hash(b"b")
    value2 = std_hash(Program.to([1, 23]))
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1, "value": value1}]
    res = await rpc_api.create_kv_store()
    store_id = res["id"]
    await rpc_api.update_kv_store({"id": store_id, "changelist": changelist})
    res = await rpc_api.get_value({"id": store_id, "key": key1})
    assert res["data"] == value1

    changelist = [{"action": "insert", "key": key2, "value": value2}]
    await rpc_api.update_kv_store({"id": store_id, "changelist": changelist})
    res = await rpc_api.get_value({"id": store_id, "key": key2})
    assert res["data"] == value2

    changelist = [{"action": "delete", "key": key1}]
    await rpc_api.update_kv_store({"id": store_id, "changelist": changelist})
    with pytest.raises(Exception):
        val = await rpc_api.get_value({"id": store_id, "key": key1})
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
    key1 = std_hash(b"a")
    value1 = std_hash(Program.to([1, 2]))
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1, "value": value1}]
    key2 = std_hash(b"b")
    value2 = std_hash(Program.to([3, 2]))
    changelist.append({"action": "insert", "key": key2, "value": value2})
    key3 = std_hash(b"c")
    value3 = std_hash(Program.to([4, 5]))
    changelist.append({"action": "insert", "key": key3, "value": value3})
    key4 = std_hash(b"d")
    value4 = std_hash(Program.to([6, 3]))
    changelist.append({"action": "insert", "key": key4, "value": value4})
    key5 = std_hash(b"e")
    value5 = std_hash(Program.to([7, 1]))
    changelist.append({"action": "insert", "key": key5, "value": value5})
    res = await rpc_api.create_kv_store()
    tree_id = res["id"]
    await rpc_api.update_kv_store({"id": tree_id, "changelist": changelist})
    val = await rpc_api.get_value({"id": tree_id, "key": key1})
    assert val["data"] == value1
    val = await rpc_api.get_value({"id": tree_id, "key": key1})
    changelist = [{"action": "delete", "key": key1}]
    await rpc_api.update_kv_store({"id": tree_id, "changelist": changelist})
    with pytest.raises(Exception):
        val = await rpc_api.get_value({"id": tree_id, "key": key1})
    await connection.close()
