from typing import List, Dict
import pytest

# flake8: noqa: F401
import aiosqlite
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_store import DataStore
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.db_wrapper import DBWrapper
from chia.util.ints import uint16
from chia.wallet.wallet_node import WalletNode
from chia.wallet.wallet_state_manager import WalletStateManager

from tests.core.data_layer.util import ChiaRoot
from tests.setup_nodes import setup_simulators_and_wallets, self_hostname


@pytest.fixture(scope="function")
async def wallet_node():
    async for _ in setup_simulators_and_wallets(1, 1, {}):
        yield _


@pytest.mark.asyncio
async def test_create_insert_get(chia_root: ChiaRoot, wallet_node):
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"

    full_nodes, wallets = wallet_node
    full_node_api = full_nodes[0]
    full_node_server = full_node_api.server
    wallet, wallet_server = wallets[0]

    # wallet_0 = wallet.wallet_state_manager.main_wallet
    # ph = await wallet_0.get_new_puzzlehash()
    # await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
    #
    # for i in range(3):
    #     await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

    data_layer = DataLayer(
        config["data_layer"],
        root_path=root,
        wallet_state_manager=wallet.wallet_state_manager,
        consensus_constants=DEFAULT_CONSTANTS,
    )
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
async def test_create_double_insert(chia_root: ChiaRoot, wallet_node):
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    wallet = wallet_node[1][0][0]
    data_layer = DataLayer(
        config["data_layer"],
        root_path=root,
        wallet_state_manager=wallet.wallet_state_manager,
        consensus_constants=DEFAULT_CONSTANTS,
    )
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
async def test_get_pairs(chia_root: ChiaRoot, wallet_node):
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    wallet = wallet_node[1][0][0]
    data_layer = DataLayer(
        config["data_layer"],
        root_path=root,
        wallet_state_manager=wallet.wallet_state_manager,
        consensus_constants=DEFAULT_CONSTANTS,
    )
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
    val = await rpc_api.get_pairs({"id": tree_id.hex()})
    # todo check values match
    await connection.close()


@pytest.mark.asyncio
async def test_get_ancestors(chia_root: ChiaRoot, wallet_node):
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    wallet = wallet_node[1][0][0]
    data_layer = DataLayer(
        config["data_layer"],
        root_path=root,
        wallet_state_manager=wallet.wallet_state_manager,
        consensus_constants=DEFAULT_CONSTANTS,
    )
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
    val = await rpc_api.get_ancestors({"id": tree_id.hex(), "key": key1.hex()})
    # todo assert values
    await connection.close()
