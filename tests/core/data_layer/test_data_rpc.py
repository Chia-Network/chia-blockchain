import asyncio
from asyncio import Future
from pathlib import Path
from typing import AsyncIterator, Dict, List, Tuple, Awaitable
from unittest.mock import Mock

import pytest

# flake8: noqa: F401
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_wallet import SingletonRecord
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.rpc.rpc_server import start_rpc_server
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.start_data_layer import service_kwargs_for_data_layer
from chia.server.start_service import Service
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_node import WalletNode
from tests.setup_nodes import setup_simulators_and_wallets, bt
from tests.time_out_assert import time_out_assert
from tests.wallet.rl_wallet.test_rl_rpc import is_transaction_confirmed

pytestmark = pytest.mark.data_layer
nodes = Tuple[WalletNode, FullNodeSimulator]


def mock_singleton() -> Awaitable[SingletonRecord]:
    mock_singleton = SingletonRecord(
        bytes32([0] * 32),
        bytes32([0] * 32),
        bytes32([0] * 32),
        bytes32([0] * 32),
        False,
        uint32(0),
        LineageProof(None, None, None),
        uint32(0),
        uint64(0),
    )
    awaitable_res: Future[SingletonRecord] = asyncio.Future()
    awaitable_res.set_result(mock_singleton)
    return awaitable_res


def mock_tx_record() -> Awaitable[TransactionRecord]:
    mock_tx = TransactionRecord(
        uint32(0),
        uint64(0),
        bytes32([0] * 32),
        uint64(0),
        uint64(0),
        False,
        uint32(0),
        None,
        [],
        [],
        uint32(0),
        [],
        bytes32([0] * 32),
        uint32(0),
        bytes32([0] * 32),
        [],
    )
    awaitable_res: Future[TransactionRecord] = asyncio.Future()
    awaitable_res.set_result(mock_tx)
    return awaitable_res


async def init_data_layer(root_path: Path) -> AsyncIterator[DataLayer]:
    test_rpc_port = uint16(21529)
    config = bt.config
    kwargs = service_kwargs_for_data_layer(root_path, config, test_rpc_port)
    kwargs.update(parse_cli_args=False)
    service = Service(**kwargs)
    await service.start()
    yield service._api.data_layer
    service.stop()
    await service.wait_closed()


@pytest.fixture(scope="function")
async def one_wallet_node() -> AsyncIterator[nodes]:
    async for _ in setup_simulators_and_wallets(1, 1, {}):
        yield _


@pytest.fixture(scope="function")
async def one_wallet_node_and_rpc() -> AsyncIterator[nodes]:
    async for nodes in setup_simulators_and_wallets(1, 1, {}):
        full_nodes, wallets = nodes
        wallet_node_0, wallet_server_0 = wallets[0]
        config = bt.config
        hostname = config["self_hostname"]
        daemon_port = config["daemon_port"]
        test_rpc_port = uint16(21529)
        rpc_cleanup = await start_rpc_server(
            WalletRpcApi(wallet_node_0),
            hostname,
            daemon_port,
            test_rpc_port,
            lambda x: None,
            bt.root_path,
            config,
            connect_to_daemon=False,
        )
        yield wallet_node_0, full_nodes[0]
        await rpc_cleanup()


@pytest.mark.asyncio
async def test_create_insert_get(one_wallet_node_and_rpc: nodes) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    assert wallet_node.wallet_state_manager is not None
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async for data_layer in init_data_layer(root_path):
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


@pytest.mark.asyncio
async def test_create_double_insert(one_wallet_node_and_rpc: nodes) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    assert wallet_node.wallet_state_manager is not None
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async for data_layer in init_data_layer(root_path):
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
async def test_keys_values_ancestors(one_wallet_node_and_rpc: nodes) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    assert wallet_node.wallet_state_manager is not None
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
    async for data_layer in init_data_layer(root_path):
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
        dic = {}
        for item in val["keys_values"]:
            dic[item["key"]] = item["value"]
        assert dic["0x" + key1.hex()] == "0x" + value1.hex()
        assert dic["0x" + key2.hex()] == "0x" + value2.hex()
        assert dic["0x" + key3.hex()] == "0x" + value3.hex()
        assert dic["0x" + key4.hex()] == "0x" + value4.hex()
        assert dic["0x" + key5.hex()] == "0x" + value5.hex()
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
        assert len(pairs_before["keys_values"]) == 5
        assert len(pairs_after["keys_values"]) == 7


@pytest.mark.asyncio
async def test_get_roots(one_wallet_node_and_rpc: nodes) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    assert wallet_node.wallet_state_manager is not None
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async for data_layer in init_data_layer(root_path):
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
async def test_get_root_history(one_wallet_node_and_rpc: nodes) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    assert wallet_node.wallet_state_manager is not None
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async for data_layer in init_data_layer(root_path):
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
async def test_get_kv_diff(one_wallet_node_and_rpc: nodes) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    assert wallet_node.wallet_state_manager is not None
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async for data_layer in init_data_layer(root_path):
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
async def test_batch_update_matches_single_operations(one_wallet_node_and_rpc: nodes) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    assert wallet_node.wallet_state_manager is not None
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )
    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    wallet_rpc_api = WalletRpcApi(wallet_node)
    async for data_layer in init_data_layer(root_path):
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
async def test_resubmit(one_wallet_node_and_rpc: nodes) -> None:
    root_path = bt.root_path
    wallet_node, full_node_api = one_wallet_node_and_rpc
    num_blocks = 15
    assert wallet_node.server
    await wallet_node.server.start_client(PeerInfo("localhost", uint16(full_node_api.server._port)), None)
    assert wallet_node.wallet_state_manager is not None
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await asyncio.sleep(0.5)
    funds = sum(
        [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
    )

    wallet_rpc_api = WalletRpcApi(wallet_node)

    await time_out_assert(15, wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance, funds)
    async for data_layer in init_data_layer(root_path):
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
        await data_rpc_api.batch_update({"id": store_id1.hex(), "changelist": changelist})
        root = await data_rpc_api.get_local_root({"id": store_id1.hex()})
        assert root["submissions"] == 1
        singleton = await wallet_rpc_api.dl_latest_singleton({"launcher_id": store_id1.hex()})
        data_layer.wallet_rpc.dl_latest_singleton = Mock(return_value=mock_singleton())  # type: ignore[assignment]
        data_layer.wallet_rpc.dl_update_root = Mock(return_value=mock_tx_record())  # type: ignore[assignment]
        await data_rpc_api.resubmit_root({"id": store_id1.hex()})
        root = await data_rpc_api.get_local_root({"id": store_id1.hex()})
        assert root["submissions"] == 2
        data_layer.wallet_rpc.dl_latest_singleton = Mock(return_value=singleton)  # type: ignore[assignment]
        with pytest.raises(Exception):
            root = await data_rpc_api.resubmit_root({"id": store_id1.hex()})
        root = await data_rpc_api.get_local_root({"id": store_id1.hex()})
        assert root["submissions"] == 2
