import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Dict, List, Set, Tuple

import pytest
import pytest_asyncio

# flake8: noqa: F401
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_util import DiffData, OperationType, Side
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi, Layer, Offer, Proof, StoreProofs
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.start_data_layer import service_kwargs_for_data_layer
from chia.server.start_service import Service
from chia.simulator.full_node_simulator import FullNodeSimulator, backoff_times
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import save_config
from chia.util.ints import uint16, uint32
from chia.wallet.wallet_node import WalletNode
from tests.block_tools import BlockTools
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert
from tests.util.socket import find_available_listen_port
from tests.wallet.rl_wallet.test_rl_rpc import is_transaction_confirmed

pytestmark = pytest.mark.data_layer
nodes = Tuple[WalletNode, FullNodeSimulator]
nodes_with_port = Tuple[WalletNode, FullNodeSimulator, int]


@contextlib.asynccontextmanager
async def init_data_layer(wallet_rpc_port: int, bt: BlockTools, db_path: Path) -> AsyncIterator[DataLayer]:
    config = bt.config
    config["data_layer"]["wallet_peer"]["port"] = wallet_rpc_port
    # TODO: running the data server causes the RPC tests to hang at the end
    config["data_layer"]["run_server"] = False
    config["data_layer"]["port"] = 0
    config["data_layer"]["rpc_port"] = 0
    config["data_layer"]["database_path"] = str(db_path.joinpath("db.sqlite"))
    save_config(bt.root_path, "config.yaml", config)
    kwargs = service_kwargs_for_data_layer(root_path=bt.root_path, config=config)
    kwargs.update(parse_cli_args=False)
    service = Service(**kwargs)
    await service.start()
    try:
        yield service._api.data_layer
    finally:
        service.stop()
        await service.wait_closed()


@pytest_asyncio.fixture(scope="function")
async def one_wallet_node() -> AsyncIterator[nodes]:
    async for _ in setup_simulators_and_wallets(1, 1, {}):
        yield _


@pytest_asyncio.fixture(scope="function")
async def one_wallet_node_and_rpc(bt: BlockTools) -> AsyncIterator[nodes_with_port]:
    async for nodes in setup_simulators_and_wallets(1, 1, {}):
        full_nodes, wallets = nodes
        wallet_node_0, wallet_server_0 = wallets[0]
        config = bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]
        rpc_cleanup, rpc_port = await start_rpc_server(
            WalletRpcApi(wallet_node_0),
            hostname,
            daemon_port,
            wallet_node_0.server._port,
            lambda: None,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        yield wallet_node_0, full_nodes[0], rpc_port
        await rpc_cleanup()


@pytest.mark.asyncio
async def test_create_insert_get(one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        # test insert
        data_rpc_api = DataLayerRpcApi(data_layer)
        key = b"a"
        value = b"\x00\x01"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32(hexstr_to_bytes(res["id"]))
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)
        res = await data_rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
        wallet_root = await data_rpc_api.get_root({"id": store_id.hex()})
        local_root = await data_rpc_api.get_local_root({"id": store_id.hex()})
        assert wallet_root["hash"] == local_root["hash"]
        assert hexstr_to_bytes(res["value"]) == value

        # test delete unknown key
        unknown_key = b"b"
        changelist = [{"action": "delete", "key": unknown_key.hex()}]
        with pytest.raises(ValueError, match="Changelist resulted in no change to tree data"):
            await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})

        # test delete
        changelist = [{"action": "delete", "key": key.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await asyncio.sleep(1)
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec1)
        with pytest.raises(Exception):
            val = await data_rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
        wallet_root = await data_rpc_api.get_root({"id": store_id.hex()})
        local_root = await data_rpc_api.get_local_root({"id": store_id.hex()})
        assert wallet_root["hash"] == bytes32([0] * 32)
        assert local_root["hash"] == None

        # test empty changelist
        changelist = []
        with pytest.raises(ValueError, match="Changelist resulted in no change to tree data"):
            await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})


@pytest.mark.asyncio
async def test_upsert(one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path) -> None:
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        # test insert
        data_rpc_api = DataLayerRpcApi(data_layer)
        key = b"a"
        value = b"\x00\x01"
        changelist: List[Dict[str, str]] = [
            {"action": "delete", "key": key.hex()},
            {"action": "insert", "key": key.hex(), "value": value.hex()},
        ]
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)
        res = await data_rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
        wallet_root = await data_rpc_api.get_root({"id": store_id.hex()})
        local_root = await data_rpc_api.get_local_root({"id": store_id.hex()})
        assert wallet_root["hash"] == local_root["hash"]
        assert hexstr_to_bytes(res["value"]) == value


@pytest.mark.asyncio
async def test_create_double_insert(one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32(hexstr_to_bytes(res["id"]))
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)

        key1 = b"a"
        value1 = b"\x01\x02"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.hex(), "value": value1.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)
        res = await data_rpc_api.get_value({"id": store_id.hex(), "key": key1.hex()})
        assert hexstr_to_bytes(res["value"]) == value1
        key2 = b"b"
        value2 = b"\x01\x23"
        changelist = [{"action": "insert", "key": key2.hex(), "value": value2.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)
        res = await data_rpc_api.get_value({"id": store_id.hex(), "key": key2.hex()})
        assert hexstr_to_bytes(res["value"]) == value2
        changelist = [{"action": "delete", "key": key1.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await asyncio.sleep(1)
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec1)
        with pytest.raises(Exception):
            val = await data_rpc_api.get_value({"id": store_id.hex(), "key": key1.hex()})


@pytest.mark.asyncio
async def test_keys_values_ancestors(one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    # TODO: with this being a pseudo context manager'ish thing it doesn't actually handle shutdown
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32(hexstr_to_bytes(res["id"]))
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
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
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)
        val = await data_rpc_api.get_keys_values({"id": store_id.hex()})
        keys = await data_rpc_api.get_keys({"id": store_id.hex()})
        dic = {}
        for item in val["keys_values"]:
            dic[item["key"]] = item["value"]
        assert dic["0x" + key1.hex()] == "0x" + value1.hex()
        assert dic["0x" + key2.hex()] == "0x" + value2.hex()
        assert dic["0x" + key3.hex()] == "0x" + value3.hex()
        assert dic["0x" + key4.hex()] == "0x" + value4.hex()
        assert dic["0x" + key5.hex()] == "0x" + value5.hex()
        assert len(keys["keys"]) == len(dic)
        for key in keys["keys"]:
            assert key in dic
        val = await data_rpc_api.get_ancestors({"id": store_id.hex(), "hash": val["keys_values"][4]["hash"]})
        # todo better assertions for get_ancestors result
        assert len(val["ancestors"]) == 3
        res_before = await data_rpc_api.get_root({"id": store_id.hex()})
        assert res_before["confirmed"] is True
        assert res_before["timestamp"] > 0
        key6 = b"tasdfsd"
        value6 = b"\x08\x02"
        changelist = [{"action": "insert", "key": key6.hex(), "value": value6.hex()}]
        key7 = b"basdff"
        value7 = b"\x09\x02"
        changelist.append({"action": "insert", "key": key7.hex(), "value": value7.hex()})
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)
        res_after = await data_rpc_api.get_root({"id": store_id.hex()})
        assert res_after["confirmed"] is True
        assert res_after["timestamp"] > res_before["timestamp"]
        pairs_before = await data_rpc_api.get_keys_values({"id": store_id.hex(), "root_hash": res_before["hash"].hex()})
        pairs_after = await data_rpc_api.get_keys_values({"id": store_id.hex(), "root_hash": res_after["hash"].hex()})
        keys_before = await data_rpc_api.get_keys({"id": store_id.hex(), "root_hash": res_before["hash"].hex()})
        keys_after = await data_rpc_api.get_keys({"id": store_id.hex(), "root_hash": res_after["hash"].hex()})
        assert len(pairs_before["keys_values"]) == len(keys_before["keys"]) == 5
        assert len(pairs_after["keys_values"]) == len(keys_after["keys"]) == 7


@pytest.mark.asyncio
async def test_get_roots(one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id1 = bytes32(hexstr_to_bytes(res["id"]))
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)

        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id2 = bytes32(hexstr_to_bytes(res["id"]))
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)

        key1 = b"a"
        value1 = b"\x01\x02"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.hex(), "value": value1.hex()}]
        key2 = b"b"
        value2 = b"\x03\x02"
        changelist.append({"action": "insert", "key": key2.hex(), "value": value2.hex()})
        key3 = b"c"
        value3 = b"\x04\x05"
        changelist.append({"action": "insert", "key": key3.hex(), "value": value3.hex()})
        res = await data_rpc_api.batch_update({"id": store_id1.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)
        roots = await data_rpc_api.get_roots({"ids": [store_id1.hex(), store_id2.hex()]})
        assert roots["root_hashes"][1]["id"] == store_id2
        assert roots["root_hashes"][1]["hash"] == bytes32([0] * 32)
        assert roots["root_hashes"][1]["confirmed"] is True
        assert roots["root_hashes"][1]["timestamp"] > 0
        key4 = b"d"
        value4 = b"\x06\x03"
        changelist = [{"action": "insert", "key": key4.hex(), "value": value4.hex()}]
        key5 = b"e"
        value5 = b"\x07\x01"
        changelist.append({"action": "insert", "key": key5.hex(), "value": value5.hex()})
        res = await data_rpc_api.batch_update({"id": store_id2.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec1)
        roots = await data_rpc_api.get_roots({"ids": [store_id1.hex(), store_id2.hex()]})
        assert roots["root_hashes"][1]["id"] == store_id2
        assert roots["root_hashes"][1]["hash"] is not None
        assert roots["root_hashes"][1]["hash"] != bytes32([0] * 32)
        assert roots["root_hashes"][1]["confirmed"] is True
        assert roots["root_hashes"][1]["timestamp"] > 0


@pytest.mark.asyncio
async def test_get_root_history(one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id1 = bytes32(hexstr_to_bytes(res["id"]))
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)

        res = await data_rpc_api.create_data_store({})
        assert res is not None

        key1 = b"a"
        value1 = b"\x01\x02"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.hex(), "value": value1.hex()}]
        key2 = b"b"
        value2 = b"\x03\x02"
        changelist.append({"action": "insert", "key": key2.hex(), "value": value2.hex()})
        key3 = b"c"
        value3 = b"\x04\x05"
        changelist.append({"action": "insert", "key": key3.hex(), "value": value3.hex()})
        res = await data_rpc_api.batch_update({"id": store_id1.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)
        history1 = await data_rpc_api.get_root_history({"id": store_id1.hex()})
        assert len(history1["root_history"]) == 2
        assert history1["root_history"][0]["root_hash"] == bytes32([0] * 32)
        assert history1["root_history"][0]["confirmed"] is True
        assert history1["root_history"][0]["timestamp"] > 0
        assert history1["root_history"][1]["root_hash"] != bytes32([0] * 32)
        assert history1["root_history"][1]["confirmed"] is True
        assert history1["root_history"][1]["timestamp"] > 0
        key4 = b"d"
        value4 = b"\x06\x03"
        changelist = [{"action": "insert", "key": key4.hex(), "value": value4.hex()}]
        key5 = b"e"
        value5 = b"\x07\x01"
        changelist.append({"action": "insert", "key": key5.hex(), "value": value5.hex()})
        res = await data_rpc_api.batch_update({"id": store_id1.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec1)
        history2 = await data_rpc_api.get_root_history({"id": store_id1.hex()})
        assert len(history2["root_history"]) == 3
        assert history2["root_history"][0]["root_hash"] == bytes32([0] * 32)
        assert history2["root_history"][0]["confirmed"] is True
        assert history2["root_history"][0]["timestamp"] > 0
        assert history2["root_history"][1]["root_hash"] == history1["root_history"][1]["root_hash"]
        assert history2["root_history"][1]["confirmed"] is True
        assert history2["root_history"][1]["timestamp"] > history2["root_history"][0]["timestamp"]
        assert history2["root_history"][2]["confirmed"] is True
        assert history2["root_history"][2]["timestamp"] > history2["root_history"][1]["timestamp"]


@pytest.mark.asyncio
async def test_get_kv_diff(one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id1 = bytes32(hexstr_to_bytes(res["id"]))
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)

        res = await data_rpc_api.create_data_store({})
        assert res is not None

        key1 = b"a"
        value1 = b"\x01\x02"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.hex(), "value": value1.hex()}]
        key2 = b"b"
        value2 = b"\x03\x02"
        changelist.append({"action": "insert", "key": key2.hex(), "value": value2.hex()})
        key3 = b"c"
        value3 = b"\x04\x05"
        changelist.append({"action": "insert", "key": key3.hex(), "value": value3.hex()})
        res = await data_rpc_api.batch_update({"id": store_id1.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)
        history = await data_rpc_api.get_root_history({"id": store_id1.hex()})
        diff_res = await data_rpc_api.get_kv_diff(
            {
                "id": store_id1.hex(),
                "hash_1": bytes32([0] * 32).hex(),
                "hash_2": history["root_history"][1]["root_hash"].hex(),
            }
        )
        assert len(diff_res["diff"]) == 3
        diff1 = {"type": "INSERT", "key": key1.hex(), "value": value1.hex()}
        diff2 = {"type": "INSERT", "key": key2.hex(), "value": value2.hex()}
        diff3 = {"type": "INSERT", "key": key3.hex(), "value": value3.hex()}
        assert diff1 in diff_res["diff"]
        assert diff2 in diff_res["diff"]
        assert diff3 in diff_res["diff"]
        key4 = b"d"
        value4 = b"\x06\x03"
        changelist = [{"action": "insert", "key": key4.hex(), "value": value4.hex()}]
        key5 = b"e"
        value5 = b"\x07\x01"
        changelist.append({"action": "insert", "key": key5.hex(), "value": value5.hex()})
        changelist.append({"action": "delete", "key": key1.hex()})
        res = await data_rpc_api.batch_update({"id": store_id1.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec1)
        history = await data_rpc_api.get_root_history({"id": store_id1.hex()})
        diff_res = await data_rpc_api.get_kv_diff(
            {
                "id": store_id1.hex(),
                "hash_1": history["root_history"][1]["root_hash"].hex(),
                "hash_2": history["root_history"][2]["root_hash"].hex(),
            }
        )
        assert len(diff_res["diff"]) == 3
        diff1 = {"type": "DELETE", "key": key1.hex(), "value": value1.hex()}
        diff4 = {"type": "INSERT", "key": key4.hex(), "value": value4.hex()}
        diff5 = {"type": "INSERT", "key": key5.hex(), "value": value5.hex()}
        assert diff4 in diff_res["diff"]
        assert diff5 in diff_res["diff"]
        assert diff1 in diff_res["diff"]


@pytest.mark.asyncio
async def test_batch_update_matches_single_operations(
    one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path
) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32(hexstr_to_bytes(res["id"]))
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)

        key = b"a"
        value = b"\x00\x01"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec0)

        key_2 = b"b"
        value_2 = b"\x00\x01"
        changelist = [{"action": "insert", "key": key_2.hex(), "value": value_2.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec1)

        key_3 = b"c"
        value_3 = b"\x00\x01"
        changelist = [{"action": "insert", "key": key_3.hex(), "value": value_3.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec2 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec2)

        changelist = [{"action": "delete", "key": key_3.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec3 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec3)

        root_1 = await data_rpc_api.get_roots({"ids": [store_id.hex()]})
        expected_res_hash = root_1["root_hashes"][0]["hash"]
        assert expected_res_hash != bytes32([0] * 32)

        changelist = [{"action": "delete", "key": key_2.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec4 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec4)

        changelist = [{"action": "delete", "key": key.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec5 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec5)

        root_2 = await data_rpc_api.get_roots({"ids": [store_id.hex()]})
        hash_2 = root_2["root_hashes"][0]["hash"]
        assert hash_2 == bytes32([0] * 32)

        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        changelist.append({"action": "insert", "key": key_2.hex(), "value": value_2.hex()})
        changelist.append({"action": "insert", "key": key_3.hex(), "value": value_3.hex()})
        changelist.append({"action": "delete", "key": key_3.hex()})

        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec6 = res["tx_id"]
        await asyncio.sleep(1)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.2)
        await time_out_assert(15, is_transaction_confirmed, True, "this is unused", wallet_rpc_api, update_tx_rec6)

        root_3 = await data_rpc_api.get_roots({"ids": [store_id.hex()]})
        batch_hash = root_3["root_hashes"][0]["hash"]
        assert batch_hash == expected_res_hash


@pytest.mark.asyncio
async def test_get_owned_stores(one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path) -> None:
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 4
    assert wallet_node.server is not None
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)

    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)

        expected_store_ids = []

        for _ in range(3):
            res = await data_rpc_api.create_data_store({})
            assert res is not None
            launcher_id = bytes32.from_hexstr(res["id"])
            expected_store_ids.append(launcher_id)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.5)

        response = await data_rpc_api.get_owned_stores(request={})
        store_ids = sorted(bytes32.from_hexstr(id) for id in response["store_ids"])

        assert store_ids == sorted(expected_store_ids)


@pytest.mark.asyncio
async def test_subscriptions(one_wallet_node_and_rpc: nodes_with_port, bt: BlockTools, tmp_path: Path) -> None:
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    num_blocks = 4
    assert wallet_node.server is not None
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)

    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)

        res = await data_rpc_api.create_data_store({})
        assert res is not None
        launcher_id = bytes32.from_hexstr(res["id"])

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.5)

        # This tests subscribe/unsubscribe to your own singletons, which isn't quite
        # the same thing as using a different wallet, but makes the tests much simpler
        response = await data_rpc_api.subscribe(request={"id": launcher_id.hex(), "urls": ["http://127:0:0:1/8000"]})
        assert response is not None

        # test subscriptions
        response = await data_rpc_api.subscriptions(request={})
        assert launcher_id.hex() in response.get("store_ids", [])

        # test unsubscribe
        response = await data_rpc_api.unsubscribe(request={"id": launcher_id.hex()})
        assert response is not None

        response = await data_rpc_api.subscriptions(request={})
        assert launcher_id.hex() not in response.get("store_ids", [])


@dataclass(frozen=True)
class OfferSetup:
    api: DataLayerRpcApi
    maker_store_id: bytes32
    taker_store_id: bytes32
    # reference_offer: Offer


@pytest_asyncio.fixture(name="offer_setup")
async def offer_setup_fixture(
    one_wallet_node_and_rpc: nodes_with_port,
    bt: BlockTools,
    tmp_path: Path,
) -> AsyncIterator[OfferSetup]:
    wallet_node, full_node_api, wallet_rpc_port = one_wallet_node_and_rpc
    assert wallet_node.server is not None
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    assert wallet_node.wallet_state_manager is not None
    wallet = wallet_node.wallet_state_manager.main_wallet

    await full_node_api.farm_blocks(count=1, wallet=wallet)

    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)

        # TODO: should we explicitly make these consistent?
        create_response = await data_rpc_api.create_data_store({})
        maker_store_id = bytes32.from_hexstr(create_response["id"])
        create_response = await data_rpc_api.create_data_store({})
        taker_store_id = bytes32.from_hexstr(create_response["id"])

        for sleep_time in backoff_times():
            await full_node_api.process_blocks(count=1)
            try:
                await data_rpc_api.get_root({"id": maker_store_id.hex()})
                await data_rpc_api.get_root({"id": taker_store_id.hex()})
            except Exception as e:
                # TODO: more specific exceptions...
                if "Failed to get root for" not in str(e):
                    raise
            else:
                break
            await asyncio.sleep(sleep_time)

        for store_id, value_prefix in {maker_store_id: b"\x01", taker_store_id: b"\x02"}.items():
            await data_rpc_api.batch_update(
                {
                    "id": store_id.hex(),
                    "changelist": [
                        {
                            "action": "insert",
                            "key": value.to_bytes(length=1, byteorder="big").hex(),
                            "value": (value_prefix + value.to_bytes(length=1, byteorder="big")).hex(),
                        }
                        for value in range(10)
                    ],
                }
            )

        for sleep_time in backoff_times():
            await full_node_api.process_blocks(count=1)

            # TODO: speeds things up but this is private...
            await data_layer._update_confirmation_status(tree_id=maker_store_id)
            await data_layer._update_confirmation_status(tree_id=taker_store_id)

            try:
                await data_layer.data_store.get_node_by_key(tree_id=maker_store_id, key=b"\x00")
                await data_layer.data_store.get_node_by_key(tree_id=taker_store_id, key=b"\x00")
            except Exception as e:
                # TODO: more specific exceptions...
                if "Key not found" not in str(e):
                    raise
            else:
                break
            await asyncio.sleep(sleep_time)
        else:
            raise Exception("failed to confirm the new data")

        yield OfferSetup(api=data_rpc_api, maker_store_id=maker_store_id, taker_store_id=taker_store_id)


reference_offer = {
    "offer": "0000000232dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa24358e72d27f0c1416251d411a7b1267e6ae30b7cd4b27eb30cb89896d7af0ce1780000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b08acbcdc220408ab0065b3d77eab2d15ea7ab6de0765287f64d97b203ff9823d4cc8dde13239531d199de4269ba7e04f6ff018080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0100ff2bff0580ffff01ff0bffff0100ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff81e8ff0bffffffffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffa057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a980ff808080ffff33ffa062aabf7c0b7031c344874808d56905934b7af4648f3e1abb30ae6941f0ab9592ff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0e518a3d0a83ef7d930e6e285d34bf9e434f58e2c81ef8fdc86ccafabc103ea268080ffff3fffa06b42b4d2452f894c8fd1e4289c0fa3b7022862fab095e753ef33be6228da82048080ffff04ffff0180ffff04ffff0180ffff04ffff0180ff018080808080ffff80ff80ff80ff80ff8080808080eb15f145cd413babe724e49c7057931bcc2da3f9c5204af89c7c609e9152be0b761f16107b673e143c50958c6c3ca2545d1b58f2a3554f91a8be2d2027ace48b0000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0e518a3d0a83ef7d930e6e285d34bf9e434f58e2c81ef8fdc86ccafabc103ea26ff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0e518a3d0a83ef7d930e6e285d34bf9e434f58e2c81ef8fdc86ccafabc103ea268080ffff3eff248080ff018080808080ff01808080ffffa032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243ffa09619cee12c35007eea85dd7b96d72236da158a1bbadcd77775941b4ae85b0073ff0180ff01ffff8080808f338522a8da7d794001c1a817ca257f4953b0d563d6cdeb8d35bf6e1ba302fac1d52af9f2ae3bcdb2532718b6149ddf07f4d16350068db3ebd584de3e9c66f48e63dc78f77dc52a4807553e3edfc897f5f17d14b995557618cf3d452e0e5b83",
    "offer_id": "264dad73d91fa8de28f44d599fe4aa96af6d8901e6dab75a31b8e046905c93d0",
    "maker": [
        {
            "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
            "proofs": [
                {
                    "key": "10",
                    "value": "0110",
                    "node_hash": "de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58",
                    # TODO: fix up layer-getting (see: 840910390980427)
                    "layers": [],
                    # "layers": [
                    #     {
                    #         "other_hash": "1c8ab812b97f5a9da0ba4be2380104810fe5c8022efe9b9e2c9d188fc3537434",
                    #         "other_hash_side": "left",
                    #         "combined_hash": "a624e12b8db06e55dcf520cedf4ff744c3aac35ebeb0b05a0f63bcb41ba8b221",
                    #     },
                    #     {
                    #         "other_hash": "6a37ca2d9a37a50f2d53387c3cf31395c72d75b1aacfa4402c32dc6d354542b4",
                    #         "other_hash_side": "right",
                    #         "combined_hash": "980a121e80381e79b37aa634758ff8a56c6cdf67c50ec0e75d14b4749dcde189",
                    #     },
                    #     {
                    #         "other_hash": "bcff6f16886339a196a2f6c842ad6d350a8579d123eb8602a0a85965ba25d671",
                    #         "other_hash_side": "right",
                    #         "combined_hash": "6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27",
                    #     },
                    # ],
                }
            ],
        }
    ],
    "taker": [
        {
            "store_id": "99d5162207159d1936a9421acf5aeb4b1154bf063583927c601cf5018b11c03c",
            "inclusions": [
                {
                    "key": "10",
                    "value": "0210",
                }
            ],
        }
    ],
}


@pytest.mark.asyncio
async def test_make_offer(offer_setup: OfferSetup) -> None:
    request = {
        "maker": [
            {
                "store_id": offer_setup.maker_store_id.hex(),
                "inclusions": [{"key": b"\x10".hex(), "value": b"\x01\x10".hex()}],
            }
        ],
        "taker": [
            {
                "store_id": offer_setup.taker_store_id.hex(),
                "inclusions": [{"key": b"\x10".hex(), "value": b"\x02\x10".hex()}],
            }
        ],
    }
    response = await offer_setup.api.make_offer(request=request)
    print(response)

    assert response == {"success": True, "offer": reference_offer}


@pytest.mark.asyncio
async def test_take_offer(offer_setup: OfferSetup) -> None:
    request = {
        "offer": reference_offer,
    }
    response = await offer_setup.api.take_offer(request=request)

    # TODO: figure out what more to check
    assert response == {
        "success": True,
        "transaction_id": reference_offer["offer_id"],
    }
