import asyncio
from typing import AsyncIterator, Dict, List, Tuple
import pytest

# flake8: noqa: F401
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.server import ChiaServer
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config
from chia.util.ints import uint16
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_node import WalletNode
from tests.core.data_layer.util import ChiaRoot
from tests.setup_nodes import setup_simulators_and_wallets, self_hostname
from tests.time_out_assert import time_out_assert
from tests.wallet.rl_wallet.test_rl_rpc import is_transaction_confirmed, is_transaction_in_mempool

pytestmark = pytest.mark.data_layer

# await time_out_assert(15, is_transaction_in_mempool, True, user_wallet_id, api_user, val["transaction_id"])
nodes = Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]]]


@pytest.fixture(scope="function")
async def one_wallet_node() -> AsyncIterator[nodes]:
    async for _ in setup_simulators_and_wallets(1, 1, {}):
        yield _


# TODO: fix this
@pytest.mark.xfail(reason="incomplete, needs caught up", strict=True)
@pytest.mark.asyncio
async def test_create_insert_get(chia_root: ChiaRoot, one_wallet_node: nodes) -> None:
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    num_blocks = 5
    full_nodes, wallets = one_wallet_node
    full_node_api = full_nodes[0]
    server_1 = full_node_api.full_node.server
    wallet_node, server_2 = wallets[0]
    assert wallet_node.wallet_state_manager is not None
    wallet = wallet_node.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()
    await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    rpc_api = WalletRpcApi(wallet_node)
    res = await rpc_api.create_data_layer({"amount": 101, "fee": 1})
    await asyncio.sleep(1)
    assert res["result"]
    tx0: TransactionRecord = res["result"][0]
    tx1: TransactionRecord = res["result"][1]
    # dl_wallet = wallet_node.data_layer.wallet
    await asyncio.sleep(1)
    # todo these should work but mempool status for these txs is empty
    # await time_out_assert(15, is_transaction_in_mempool, True, tx1.wallet_id, rpc_api, tx1.name)
    # await time_out_assert(15, is_transaction_in_mempool, True, tx0.wallet_id, rpc_api, tx0.name)
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(15, is_transaction_confirmed, True, tx0.wallet_id, rpc_api, tx0.name)
    await time_out_assert(15, is_transaction_confirmed, True, tx1.wallet_id, rpc_api, tx1.name)
    key = b"a"
    value = b"\x00\x01"
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
    res = await rpc_api.create_kv_store()
    await asyncio.sleep(1)
    assert res is not None
    store_id = bytes32(hexstr_to_bytes(res["id"]))
    update_tx_rec0 = await rpc_api.update_kv_store({"id": store_id.hex(), "changelist": changelist})
    await asyncio.sleep(1)
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(15, is_transaction_confirmed, True, update_tx_rec0.wallet_id, rpc_api, update_tx_rec0.name)
    res = await rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
    assert hexstr_to_bytes(res["data"]) == value
    changelist = [{"action": "delete", "key": key.hex()}]
    update_tx_rec1 = await rpc_api.update_kv_store({"id": store_id.hex(), "changelist": changelist})
    await asyncio.sleep(1)
    for i in range(0, num_blocks):
        await asyncio.sleep(1)
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(15, is_transaction_confirmed, True, update_tx_rec1.wallet_id, rpc_api, update_tx_rec1.name)
    with pytest.raises(Exception):
        val = await rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})


# TODO: fix this
@pytest.mark.xfail(reason="incomplete, needs caught up", strict=True)
@pytest.mark.asyncio
async def test_create_double_insert(chia_root: ChiaRoot, one_wallet_node: nodes) -> None:
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    num_blocks = 5
    full_nodes, wallets = one_wallet_node
    full_node_api = full_nodes[0]
    server_1 = full_node_api.full_node.server
    wallet_node, server_2 = wallets[0]
    assert wallet_node.wallet_state_manager is not None
    wallet = wallet_node.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()
    await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    print(f"confirmed balance is {await wallet.get_confirmed_balance()}")
    print(f"unconfirmed balance is {await wallet.get_unconfirmed_balance()}")

    rpc_api = WalletRpcApi(wallet_node)
    res = await rpc_api.start_data_layer()  # type: ignore[attr-defined]
    assert res["result"] is True
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


# TODO: fix this
@pytest.mark.xfail(reason="incomplete, needs caught up", strict=True)
@pytest.mark.asyncio
async def test_get_pairs(chia_root: ChiaRoot, one_wallet_node: nodes) -> None:
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    num_blocks = 5
    full_nodes, wallets = one_wallet_node
    full_node_api = full_nodes[0]
    server_1 = full_node_api.full_node.server
    wallet_node, server_2 = wallets[0]
    assert wallet_node.wallet_state_manager is not None
    wallet = wallet_node.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()

    await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    print(f"confirmed balance is {await wallet.get_confirmed_balance()}")
    print(f"unconfirmed balance is {await wallet.get_unconfirmed_balance()}")
    rpc_api = WalletRpcApi(wallet_node)
    res = await rpc_api.start_data_layer()  # type: ignore[attr-defined]
    assert res["result"] is True
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


# TODO: fix this
@pytest.mark.xfail(reason="incomplete, needs caught up", strict=True)
@pytest.mark.asyncio
async def test_get_ancestors(chia_root: ChiaRoot, one_wallet_node: nodes) -> None:
    root = chia_root.path
    config = load_config(root, "config.yaml")
    config["data_layer"]["database_path"] = "data_layer_test.sqlite"
    num_blocks = 5
    full_nodes, wallets = one_wallet_node
    full_node_api = full_nodes[0]
    server_1 = full_node_api.full_node.server
    wallet_node, server_2 = wallets[0]
    assert wallet_node.wallet_state_manager
    wallet = wallet_node.wallet_state_manager.main_wallet
    ph = await wallet.get_new_puzzlehash()
    await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    print(f"confirmed balance is {await wallet.get_confirmed_balance()}")
    print(f"unconfirmed balance is {await wallet.get_unconfirmed_balance()}")
    rpc_api = WalletRpcApi(wallet_node)
    res = await rpc_api.start_data_layer()  # type: ignore[attr-defined]
    assert res["result"] is True
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
