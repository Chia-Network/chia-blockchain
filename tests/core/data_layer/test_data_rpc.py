from typing import List, Dict
import pytest

import aiosqlite
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_store import DataStore
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.types.blockchain_format.program import Program
from chia.util.config import load_config
from chia.util.db_wrapper import DBWrapper
from tests.core.data_layer.test_data_cli import ChiaRoot, chia_root_fixture


@pytest.mark.asyncio
async def test_create_insert_get(chia_root: ChiaRoot) -> None:
    """Create a table, insert a row, get the row by its hash."""
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
    tree_id = res["id"]
    await rpc_api.update_kv_store({"id": tree_id, "changelist": changelist})
    val = await rpc_api.get_value({"id": tree_id, "key": key.as_bin()})
    print(val)
    assert val["data"].value == value
    changelist = [{"action": "delete", "key": key.as_bin()}]
    await rpc_api.update_kv_store({"id": tree_id, "changelist": changelist})
    with pytest.raises(Exception):
        val = await rpc_api.get_value({"id": tree_id, "key": key.as_bin()})
    await connection.close()
