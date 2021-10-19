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
    key = Program.to("abc")
    value = Program.to([1, 2])
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.as_bin(), "value": value.as_bin()}]
    res = await rpc_api.create_kv_store()
    store_id = res["id"]
    await rpc_api.update_kv_store({"id": store_id, "changelist": changelist})
    res = await rpc_api.get_value({"id": store_id, "key": key.as_bin()})
    assert res["data"] == value
    changelist = [{"action": "delete", "key": key.as_bin()}]
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
    key1 = Program.to("ab")
    value1 = Program.to([1, 2])
    key2 = Program.to("ac")
    value2 = Program.to([4, 2])
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.as_bin(), "value": value1.as_bin()}]
    res = await rpc_api.create_kv_store()
    store_id = res["id"]
    await rpc_api.update_kv_store({"id": store_id, "changelist": changelist})
    res = await rpc_api.get_value({"id": store_id, "key": key1.as_bin()})
    assert res["data"] == value1

    changelist = [{"action": "insert", "key": key2.as_bin(), "value": value2.as_bin()}]
    await rpc_api.update_kv_store({"id": store_id, "changelist": changelist})
    res = await rpc_api.get_value({"id": store_id, "key": key2.as_bin()})
    assert res["data"] == value1

    changelist = [{"action": "delete", "key": key1.as_bin()}]
    await rpc_api.update_kv_store({"id": store_id, "changelist": changelist})
    with pytest.raises(Exception):
        val = await rpc_api.get_value({"id": store_id, "key": key1.as_bin()})
    await connection.close()


# @pytest.mark.skip("batches are currently broken")
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
    key1 = Program.to("a")
    value1 = Program.to([1, 2])
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.as_bin(), "value": value1.as_bin()}]
    key2 = Program.to("b")
    value2 = Program.to([3, 2])
    changelist.append({"action": "insert", "key": key2.as_bin(), "value": value2.as_bin()})
    key3 = Program.to("c")
    value3 = Program.to([4, 5])
    changelist.append({"action": "insert", "key": key3.as_bin(), "value": value3.as_bin()})
    key4 = Program.to("d")
    value4 = Program.to([6, 3])
    changelist.append({"action": "insert", "key": key4.as_bin(), "value": value4.as_bin()})
    key5 = Program.to("e")
    value5 = Program.to([7, 1])
    changelist.append({"action": "insert", "key": key5.as_bin(), "value": value5.as_bin()})
    res = await rpc_api.create_kv_store()
    tree_id = res["id"]
    await rpc_api.update_kv_store({"id": tree_id, "changelist": changelist})
    val = await rpc_api.get_value({"id": tree_id, "key": key1.as_bin()})
    assert val["data"].value == value1
    val = await rpc_api.get_value({"id": tree_id, "key": key1.as_bin()})
    # changelist = [{"action": "delete", "key": key.as_bin()}]
    # await rpc_api.update_kv_store({"id": tree_id, "changelist": changelist})
    # with pytest.raises(Exception):
    #     val = await rpc_api.get_value({"id": tree_id, "key": key.as_bin()})
    await connection.close()
