from __future__ import annotations

import asyncio
import contextlib
import copy
import enum
import json
import logging
import os
import random
import sqlite3
import sys
import time
from copy import deepcopy
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple, cast

import anyio
import pytest

from chia._tests.util.misc import boolean_datacases
from chia._tests.util.setup_nodes import SimulatorsAndWalletsServices
from chia._tests.util.time_out_assert import time_out_assert
from chia.cmds.data_funcs import (
    clear_pending_roots,
    get_keys_cmd,
    get_keys_values_cmd,
    get_kv_diff_cmd,
    get_proof_cmd,
    submit_all_pending_roots_cmd,
    submit_pending_root_cmd,
    update_data_store_cmd,
    update_multiple_stores_cmd,
    verify_proof_cmd,
    wallet_log_in_cmd,
)
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_errors import KeyNotFoundError, OfferIntegrityError
from chia.data_layer.data_layer_util import (
    HashOnlyProof,
    OfferStore,
    ProofLayer,
    Status,
    StoreProofs,
    key_hash,
    leaf_hash,
)
from chia.data_layer.data_layer_wallet import DataLayerWallet, verify_offer
from chia.data_layer.data_store import DataStore
from chia.data_layer.download_data import get_delta_filename_path, get_full_tree_filename_path
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.rpc.data_layer_rpc_client import DataLayerRpcClient
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.start_data_layer import create_data_layer_service
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.aliases import DataLayerService, WalletService
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import save_config
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.util.keychain import bytes_to_mnemonic
from chia.util.timing import adjusted_timeout, backoff_times
from chia.wallet.trading.offer import Offer as TradingOffer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_node import WalletNode

pytestmark = pytest.mark.data_layer
nodes = Tuple[WalletNode, FullNodeSimulator]
nodes_with_port_bt_ph = Tuple[WalletRpcApi, FullNodeSimulator, uint16, bytes32, BlockTools]
wallet_and_port_tuple = Tuple[WalletNode, uint16]
two_wallets_with_port = Tuple[Tuple[wallet_and_port_tuple, wallet_and_port_tuple], FullNodeSimulator, BlockTools]


class InterfaceLayer(enum.Enum):
    direct = enum.auto()
    client = enum.auto()
    funcs = enum.auto()
    cli = enum.auto()


@contextlib.asynccontextmanager
async def init_data_layer_service(
    wallet_rpc_port: uint16,
    bt: BlockTools,
    db_path: Optional[Path] = None,
    wallet_service: Optional[WalletService] = None,
    manage_data_interval: int = 5,
    maximum_full_file_count: Optional[int] = None,
    enable_batch_autoinsert: bool = True,
    group_files_by_store: bool = False,
) -> AsyncIterator[DataLayerService]:
    config = bt.config
    config["data_layer"]["wallet_peer"]["port"] = int(wallet_rpc_port)
    # TODO: running the data server causes the RPC tests to hang at the end
    config["data_layer"]["run_server"] = False
    config["data_layer"]["port"] = 0
    config["data_layer"]["rpc_port"] = 0
    config["data_layer"]["manage_data_interval"] = 5
    config["data_layer"]["enable_batch_autoinsert"] = enable_batch_autoinsert
    config["data_layer"]["group_files_by_store"] = group_files_by_store
    if maximum_full_file_count is not None:
        config["data_layer"]["maximum_full_file_count"] = maximum_full_file_count
    if db_path is not None:
        config["data_layer"]["database_path"] = str(db_path.joinpath("db.sqlite"))
    config["data_layer"]["manage_data_interval"] = manage_data_interval
    save_config(bt.root_path, "config.yaml", config)
    service = create_data_layer_service(
        root_path=bt.root_path, config=config, wallet_service=wallet_service, downloaders=[], uploaders=[]
    )
    async with service.manage():
        yield service


@contextlib.asynccontextmanager
async def init_data_layer(
    wallet_rpc_port: uint16,
    bt: BlockTools,
    db_path: Path,
    wallet_service: Optional[WalletService] = None,
    manage_data_interval: int = 5,
    maximum_full_file_count: Optional[int] = None,
    group_files_by_store: bool = False,
) -> AsyncIterator[DataLayer]:
    async with init_data_layer_service(
        wallet_rpc_port,
        bt,
        db_path,
        wallet_service,
        manage_data_interval,
        maximum_full_file_count,
        True,
        group_files_by_store,
    ) as data_layer_service:
        yield data_layer_service._api.data_layer


@pytest.fixture(name="bare_data_layer_api")
async def bare_data_layer_api_fixture(tmp_path: Path, bt: BlockTools) -> AsyncIterator[DataLayerRpcApi]:
    # we won't use this port, this fixture is for _just_ a data layer rpc
    port = uint16(1)
    async with init_data_layer(wallet_rpc_port=port, bt=bt, db_path=tmp_path.joinpath(str(port))) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        yield data_rpc_api


async def init_wallet_and_node(
    self_hostname: str, one_wallet_and_one_simulator: SimulatorsAndWalletsServices
) -> nodes_with_port_bt_ph:
    [full_node_service], [wallet_service], bt = one_wallet_and_one_simulator
    wallet_node = wallet_service._node
    full_node_api = full_node_service._api
    await wallet_node.server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    funds = calculate_pool_reward(uint32(1)) + calculate_base_farmer_reward(uint32(1))
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=20)
    balance = await wallet_node.wallet_state_manager.main_wallet.get_confirmed_balance()
    assert balance == funds
    wallet_rpc_api = WalletRpcApi(wallet_node)
    assert wallet_service.rpc_server is not None
    return wallet_rpc_api, full_node_api, wallet_service.rpc_server.listen_port, ph, bt


async def farm_block_check_singleton(
    data_layer: DataLayer, full_node_api: FullNodeSimulator, ph: bytes32, store_id: bytes32, wallet: WalletNode
) -> None:
    await time_out_assert(10, check_mempool_spend_count, True, full_node_api, 1)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(10, check_singleton_confirmed, True, data_layer, store_id)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet, timeout=20)


async def is_transaction_confirmed(api: WalletRpcApi, tx_id: bytes32) -> bool:
    try:
        val = await api.get_transaction({"transaction_id": tx_id.hex()})
    except ValueError:  # pragma: no cover
        return False

    return True if TransactionRecord.from_json_dict_convenience(val["transaction"]).confirmed else False  # mypy


async def farm_block_with_spend(
    full_node_api: FullNodeSimulator, ph: bytes32, tx_rec: bytes32, wallet_rpc_api: WalletRpcApi
) -> None:
    await time_out_assert(10, check_mempool_spend_count, True, full_node_api, 1)
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    await time_out_assert(10, is_transaction_confirmed, True, wallet_rpc_api, tx_rec)
    await full_node_api.wait_for_wallet_synced(wallet_node=wallet_rpc_api.service, timeout=20)


def check_mempool_spend_count(full_node_api: FullNodeSimulator, num_of_spends: int) -> bool:
    return full_node_api.full_node.mempool_manager.mempool.size() == num_of_spends


async def check_coin_state(wallet_node: WalletNode, coin_id: bytes32) -> bool:
    coin_states = await wallet_node.get_coin_state([coin_id], wallet_node.get_full_node_peer())

    if len(coin_states) == 1 and coin_states[0].coin.name() == coin_id:
        return True

    return False  # pragma: no cover


async def check_singleton_confirmed(dl: DataLayer, store_id: bytes32) -> bool:
    return await dl.wallet_rpc.dl_latest_singleton(store_id, True) is not None


async def process_block_and_check_offer_validity(offer: TradingOffer, offer_setup: OfferSetup) -> bool:
    await offer_setup.full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
    return (await offer_setup.maker.data_layer.wallet_rpc.check_offer_validity(offer=offer))[1]


async def run_cli_cmd(*args: str, root_path: Path) -> asyncio.subprocess.Process:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "chia",
        *args,
        env={**os.environ, "CHIA_ROOT": os.fspath(root_path)},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await process.wait()
    assert process.stdout is not None
    assert process.stderr is not None
    stderr = await process.stderr.read()
    if sys.version_info >= (3, 10, 6):
        assert stderr == b""
    else:  # pragma: no cover
        # https://github.com/python/cpython/issues/92841
        assert stderr == b"" or b"_ProactorBasePipeTransport.__del__" in stderr
    assert process.returncode == 0

    return process


def create_mnemonic(seed: bytes = b"ab") -> str:
    random_ = random.Random()
    random_.seed(a=seed, version=2)
    return bytes_to_mnemonic(mnemonic_bytes=bytes(random_.randrange(256) for _ in range(32)))


@pytest.mark.anyio
async def test_create_insert_get(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        # test insert
        data_rpc_api = DataLayerRpcApi(data_layer)
        key = b"a"
        value = b"\x00\x01"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
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

        # test upsert
        new_value = b"\x00\x02"
        changelist = [{"action": "upsert", "key": key.hex(), "value": new_value.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)
        res = await data_rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
        assert hexstr_to_bytes(res["value"]) == new_value
        wallet_root = await data_rpc_api.get_root({"id": store_id.hex()})
        upsert_wallet_root = wallet_root["hash"]

        # test upsert unknown key acts as insert
        new_value = b"\x00\x02"
        changelist = [{"action": "upsert", "key": unknown_key.hex(), "value": new_value.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec2 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec2, wallet_rpc_api)
        res = await data_rpc_api.get_value({"id": store_id.hex(), "key": unknown_key.hex()})
        assert hexstr_to_bytes(res["value"]) == new_value

        # test delete
        changelist = [{"action": "delete", "key": unknown_key.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec3 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec3, wallet_rpc_api)
        with pytest.raises(Exception):
            await data_rpc_api.get_value({"id": store_id.hex(), "key": unknown_key.hex()})
        wallet_root = await data_rpc_api.get_root({"id": store_id.hex()})
        assert wallet_root["hash"] == upsert_wallet_root

        changelist = [{"action": "delete", "key": key.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec4 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec4, wallet_rpc_api)
        with pytest.raises(Exception):
            await data_rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
        wallet_root = await data_rpc_api.get_root({"id": store_id.hex()})
        local_root = await data_rpc_api.get_local_root({"id": store_id.hex()})
        assert wallet_root["hash"] == bytes32([0] * 32)
        assert local_root["hash"] is None

        # test empty changelist
        changelist = []
        with pytest.raises(ValueError, match="Changelist resulted in no change to tree data"):
            await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})


@pytest.mark.anyio
async def test_upsert(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
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
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
        res = await data_rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
        wallet_root = await data_rpc_api.get_root({"id": store_id.hex()})
        local_root = await data_rpc_api.get_local_root({"id": store_id.hex()})
        assert wallet_root["hash"] == local_root["hash"]
        assert hexstr_to_bytes(res["value"]) == value


@pytest.mark.anyio
async def test_create_double_insert(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)
        key1 = b"a"
        value1 = b"\x01\x02"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.hex(), "value": value1.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
        res = await data_rpc_api.get_value({"id": store_id.hex(), "key": key1.hex()})
        assert hexstr_to_bytes(res["value"]) == value1
        key2 = b"b"
        value2 = b"\x01\x23"
        changelist = [{"action": "insert", "key": key2.hex(), "value": value2.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)
        res = await data_rpc_api.get_value({"id": store_id.hex(), "key": key2.hex()})
        assert hexstr_to_bytes(res["value"]) == value2
        changelist = [{"action": "delete", "key": key1.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec2 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec2, wallet_rpc_api)
        with pytest.raises(Exception):
            await data_rpc_api.get_value({"id": store_id.hex(), "key": key1.hex()})


@pytest.mark.anyio
async def test_keys_values_ancestors(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    # TODO: with this being a pseudo context manager'ish thing it doesn't actually handle shutdown
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)
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
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
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
        update_tx_rec1 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)
        res_after = await data_rpc_api.get_root({"id": store_id.hex()})
        assert res_after["confirmed"] is True
        assert res_after["timestamp"] > res_before["timestamp"]
        pairs_before = await data_rpc_api.get_keys_values({"id": store_id.hex(), "root_hash": res_before["hash"].hex()})
        pairs_after = await data_rpc_api.get_keys_values({"id": store_id.hex(), "root_hash": res_after["hash"].hex()})
        keys_before = await data_rpc_api.get_keys({"id": store_id.hex(), "root_hash": res_before["hash"].hex()})
        keys_after = await data_rpc_api.get_keys({"id": store_id.hex(), "root_hash": res_after["hash"].hex()})
        assert len(pairs_before["keys_values"]) == len(keys_before["keys"]) == 5
        assert len(pairs_after["keys_values"]) == len(keys_after["keys"]) == 7

        with pytest.raises(Exception, match="Can't find keys"):
            await data_rpc_api.get_keys({"id": store_id.hex(), "root_hash": bytes32([0] * 31 + [1]).hex()})
        with pytest.raises(Exception, match="Can't find keys and values"):
            await data_rpc_api.get_keys_values({"id": store_id.hex(), "root_hash": bytes32([0] * 31 + [1]).hex()})


@pytest.mark.anyio
async def test_get_roots(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id1 = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id1, wallet=wallet_rpc_api.service)

        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id2 = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id2, wallet=wallet_rpc_api.service)

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
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
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
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)
        roots = await data_rpc_api.get_roots({"ids": [store_id1.hex(), store_id2.hex()]})
        assert roots["root_hashes"][1]["id"] == store_id2
        assert roots["root_hashes"][1]["hash"] is not None
        assert roots["root_hashes"][1]["hash"] != bytes32([0] * 32)
        assert roots["root_hashes"][1]["confirmed"] is True
        assert roots["root_hashes"][1]["timestamp"] > 0


@pytest.mark.anyio
async def test_get_root_history(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id1 = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id1, wallet=wallet_rpc_api.service)
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
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
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
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)
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


@pytest.mark.anyio
async def test_get_kv_diff(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id1 = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id1, wallet=wallet_rpc_api.service)
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
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
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
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)
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


@pytest.mark.anyio
async def test_batch_update_matches_single_operations(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)

        key = b"a"
        value = b"\x00\x01"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)

        key_2 = b"b"
        value_2 = b"\x00\x01"
        changelist = [{"action": "insert", "key": key_2.hex(), "value": value_2.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)

        key_3 = b"c"
        value_3 = b"\x00\x01"
        changelist = [{"action": "insert", "key": key_3.hex(), "value": value_3.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec2 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec2, wallet_rpc_api)

        changelist = [{"action": "delete", "key": key_3.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec3 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec3, wallet_rpc_api)

        root_1 = await data_rpc_api.get_roots({"ids": [store_id.hex()]})
        expected_res_hash = root_1["root_hashes"][0]["hash"]
        assert expected_res_hash != bytes32([0] * 32)

        changelist = [{"action": "delete", "key": key_2.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec4 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec4, wallet_rpc_api)

        changelist = [{"action": "delete", "key": key.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec5 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec5, wallet_rpc_api)

        root_2 = await data_rpc_api.get_roots({"ids": [store_id.hex()]})
        hash_2 = root_2["root_hashes"][0]["hash"]
        assert hash_2 == bytes32([0] * 32)

        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        changelist.append({"action": "insert", "key": key_2.hex(), "value": value_2.hex()})
        changelist.append({"action": "insert", "key": key_3.hex(), "value": value_3.hex()})
        changelist.append({"action": "delete", "key": key_3.hex()})

        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec6 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec6, wallet_rpc_api)

        root_3 = await data_rpc_api.get_roots({"ids": [store_id.hex()]})
        batch_hash = root_3["root_hashes"][0]["hash"]
        assert batch_hash == expected_res_hash


@pytest.mark.anyio
async def test_get_owned_stores(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    [full_node_service], [wallet_service], bt = one_wallet_and_one_simulator_services
    num_blocks = 4
    wallet_node = wallet_service._node
    assert wallet_service.rpc_server is not None
    wallet_rpc_port = wallet_service.rpc_server.listen_port
    full_node_api = full_node_service._api
    await wallet_node.server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    ph = await wallet_node.wallet_state_manager.main_wallet.get_new_puzzlehash()
    for i in range(0, num_blocks):
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    funds = sum(
        calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)
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

        await time_out_assert(4, check_mempool_spend_count, True, full_node_api, 3)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await asyncio.sleep(0.5)

        response = await data_rpc_api.get_owned_stores(request={})
        store_ids = sorted(bytes32.from_hexstr(id) for id in response["store_ids"])

        assert store_ids == sorted(expected_store_ids)


@pytest.mark.anyio
async def test_subscriptions(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )

    interval = 1
    config = bt.config
    config["data_layer"]["manage_data_interval"] = interval
    bt.change_config(new_config=config)

    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)

        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)

        # This tests subscribe/unsubscribe to your own singletons, which isn't quite
        # the same thing as using a different wallet, but makes the tests much simpler
        response = await data_rpc_api.subscribe(request={"id": store_id.hex(), "urls": ["http://127.0.0.1/8000"]})
        assert response is not None

        # test subscriptions
        response = await data_rpc_api.subscriptions(request={})
        assert store_id.hex() in response.get("store_ids", [])

        # test unsubscribe
        response = await data_rpc_api.unsubscribe(request={"id": store_id.hex()})
        assert response is not None

        # wait for unsubscribe to be processed
        await asyncio.sleep(interval * 5)

        response = await data_rpc_api.subscriptions(request={})
        assert store_id.hex() not in response.get("store_ids", [])


@dataclass(frozen=True)
class StoreSetup:
    api: DataLayerRpcApi
    id: bytes32
    original_hash: bytes32
    data_layer: DataLayer
    data_rpc_client: DataLayerRpcClient


@dataclass(frozen=True)
class OfferSetup:
    maker: StoreSetup
    taker: StoreSetup
    full_node_api: FullNodeSimulator


@pytest.fixture(name="offer_setup")
async def offer_setup_fixture(
    self_hostname: str,
    two_wallet_nodes_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> AsyncIterator[OfferSetup]:
    [full_node_service], wallet_services, bt = two_wallet_nodes_services
    enable_batch_autoinsertion_settings = getattr(request, "param", (True, True))
    full_node_api = full_node_service._api
    wallets: List[Wallet] = []
    for wallet_service in wallet_services:
        wallet_node = wallet_service._node
        assert wallet_node.server is not None
        await wallet_node.server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
        assert wallet_node.wallet_state_manager is not None
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallets.append(wallet)

        await full_node_api.farm_blocks_to_wallet(count=1, wallet=wallet, timeout=60)

    async with contextlib.AsyncExitStack() as exit_stack:
        store_setups: List[StoreSetup] = []
        for enable_batch_autoinsert, wallet_service in zip(enable_batch_autoinsertion_settings, wallet_services):
            assert wallet_service.rpc_server is not None
            port = wallet_service.rpc_server.listen_port
            data_layer_service = await exit_stack.enter_async_context(
                init_data_layer_service(
                    wallet_rpc_port=port,
                    wallet_service=wallet_service,
                    bt=bt,
                    db_path=tmp_path.joinpath(str(port)),
                    enable_batch_autoinsert=enable_batch_autoinsert,
                )
            )
            data_layer = data_layer_service._api.data_layer
            data_rpc_api = DataLayerRpcApi(data_layer)
            assert data_layer_service.rpc_server is not None
            data_rpc_client = await DataLayerRpcClient.create(
                self_hostname,
                port=data_layer_service.rpc_server.listen_port,
                root_path=bt.root_path,
                net_config=bt.config,
            )

            create_response = await data_rpc_api.create_data_store({"verbose": True})
            await full_node_api.process_transaction_records(records=create_response["txs"], timeout=60)

            store_setups.append(
                StoreSetup(
                    api=data_rpc_api,
                    id=bytes32.from_hexstr(create_response["id"]),
                    original_hash=bytes32([0] * 32),
                    data_layer=data_layer,
                    data_rpc_client=data_rpc_client,
                )
            )

        [maker, taker] = store_setups

        for sleep_time in backoff_times():
            await full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True, timeout=30)
            try:
                await maker.api.get_root({"id": maker.id.hex()})
                await taker.api.get_root({"id": taker.id.hex()})
            except Exception as e:
                # TODO: more specific exceptions...
                if "Failed to get root for" not in str(e):
                    raise  # pragma: no cover
            else:
                break
            await asyncio.sleep(sleep_time)

        # this checks that the node has the coin states for both launchers
        await time_out_assert(30, check_coin_state, True, wallet_services[0]._node, taker.id)
        await time_out_assert(30, check_coin_state, True, wallet_services[1]._node, maker.id)

        await maker.api.subscribe(request={"id": taker.id.hex(), "urls": ["http://127.0.0.1/8000"]})
        await taker.api.subscribe(request={"id": maker.id.hex(), "urls": ["http://127.0.0.1/8000"]})

        maker_original_singleton = await maker.data_layer.get_root(store_id=maker.id)
        assert maker_original_singleton is not None
        maker_original_root_hash = maker_original_singleton.root

        taker_original_singleton = await taker.data_layer.get_root(store_id=taker.id)
        assert taker_original_singleton is not None
        taker_original_root_hash = taker_original_singleton.root

        yield OfferSetup(
            maker=StoreSetup(
                api=maker.api,
                id=maker.id,
                original_hash=maker_original_root_hash,
                data_layer=maker.data_layer,
                data_rpc_client=maker.data_rpc_client,
            ),
            taker=StoreSetup(
                api=taker.api,
                id=taker.id,
                original_hash=taker_original_root_hash,
                data_layer=taker.data_layer,
                data_rpc_client=taker.data_rpc_client,
            ),
            full_node_api=full_node_api,
        )

        maker.data_rpc_client.close()
        await maker.data_rpc_client.await_closed()
        taker.data_rpc_client.close()
        await taker.data_rpc_client.await_closed()


async def populate_offer_setup(offer_setup: OfferSetup, count: int) -> OfferSetup:
    if count > 0:
        setups: Tuple[Tuple[StoreSetup, bytes], Tuple[StoreSetup, bytes]] = (
            (offer_setup.maker, b"\x01"),
            (offer_setup.taker, b"\x02"),
        )
        for store_setup, value_prefix in setups:
            await store_setup.data_layer.batch_insert(
                store_id=store_setup.id,
                changelist=[
                    {
                        "action": "insert",
                        "key": value.to_bytes(length=1, byteorder="big"),
                        "value": (value_prefix + value.to_bytes(length=1, byteorder="big")),
                    }
                    for value in range(count)
                ],
                status=Status.PENDING,
                enable_batch_autoinsert=False,
            )
            await store_setup.data_layer.publish_update(store_setup.id, uint64(0))

        await process_for_data_layer_keys(
            expected_key=b"\x00",
            full_node_api=offer_setup.full_node_api,
            data_layer=offer_setup.maker.data_layer,
            store_id=offer_setup.maker.id,
        )
        await process_for_data_layer_keys(
            expected_key=b"\x00",
            full_node_api=offer_setup.full_node_api,
            data_layer=offer_setup.taker.data_layer,
            store_id=offer_setup.taker.id,
        )

    maker_original_singleton = await offer_setup.maker.data_layer.get_root(store_id=offer_setup.maker.id)
    assert maker_original_singleton is not None
    maker_original_root_hash = maker_original_singleton.root

    taker_original_singleton = await offer_setup.taker.data_layer.get_root(store_id=offer_setup.taker.id)
    assert taker_original_singleton is not None
    taker_original_root_hash = taker_original_singleton.root

    return OfferSetup(
        maker=StoreSetup(
            api=offer_setup.maker.api,
            id=offer_setup.maker.id,
            original_hash=maker_original_root_hash,
            data_layer=offer_setup.maker.data_layer,
            data_rpc_client=offer_setup.maker.data_rpc_client,
        ),
        taker=StoreSetup(
            api=offer_setup.taker.api,
            id=offer_setup.taker.id,
            original_hash=taker_original_root_hash,
            data_layer=offer_setup.taker.data_layer,
            data_rpc_client=offer_setup.taker.data_rpc_client,
        ),
        full_node_api=offer_setup.full_node_api,
    )


async def process_for_data_layer_keys(
    expected_key: bytes,
    full_node_api: FullNodeSimulator,
    data_layer: DataLayer,
    store_id: bytes32,
    expected_value: Optional[bytes] = None,
) -> None:
    for sleep_time in backoff_times():
        try:
            value = await data_layer.get_value(store_id=store_id, key=expected_key)
        except Exception as e:
            # TODO: more specific exceptions...
            if "Key not found" not in str(e):
                raise  # pragma: no cover
        else:
            if expected_value is None or value == expected_value:
                break
        await full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True, timeout=60)
        await asyncio.sleep(sleep_time)
    else:
        raise Exception("failed to confirm the new data")  # pragma: no cover


@dataclass(frozen=True)
class MakeAndTakeReference:
    entries_to_insert: int
    make_offer_response: Dict[str, Any]
    maker_inclusions: List[Dict[str, Any]]
    maker_root_history: List[bytes32]
    taker_inclusions: List[Dict[str, Any]]
    taker_root_history: List[bytes32]
    trade_id: str


make_one_take_one_reference = MakeAndTakeReference(
    entries_to_insert=10,
    make_offer_response={
        "trade_id": "b34b77304778961deca03bd5eb370ed35a7aa97c0e030b293d1285b74d1741f4",
        "offer": "00000003000000000000000000000000000000000000000000000000000000000000000052eba05592a7cbe77b4b1552cacec440b20d523d08a6be917c9213dc34f3033a0000000000000000ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa042f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff018080808080ff01808080ffffa00000000000000000000000000000000000000000000000000000000000000000ffffa00000000000000000000000000000000000000000000000000000000000000000ff01ff80808080ca2e21c90d263e63b73d449a3f8d57b9458846f7af27d9a61a515395fa14071ea55bba78c76265b4bac257251b1e89dd13637a7c18e8dcb03e092dfb7eb5a84a0000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2aff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2a8080ffff3eff248080ff018080808080ff01808080ffffa032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243ffa08c4aebb18e8ce08405083c3d90a29f30239865142e2dcbca5393f40df9e3821dff0180ff01ffff80808032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243aa064e96a86637d8f5ebe153dc8645d29f43bee762d5ec10d06c8617fa60b8c50000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a132fae32c98cbb7d8f5814c49ee3f0ba6ec2172c5e5f6900655a65cd2157a06a1c6eb89c68c8d2cdcee9506c2217978ff018080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0102ff2bff0580ffff01ff0bffff0102ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff3fffa0bd7aa54c5f93ef1738439aa60b471ce2aa4c62fb18a7943aa10061f00dbdb83680ffff81e8ff0bffffffffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffa057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a980ff808080ffff33ffa0ca77e42ac3b3375edc54af271f21d075afd02d72969cababeec63e22f7ab10deff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0ca77e42ac3b3375edc54af271f21d075afd02d72969cababeec63e22f7ab10de808080ffff04ffff01ffffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da980ffff04ffff01ffa0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c280ffff04ffff01ffffa07f3e180acdf046f955d3440bb3a16dfd6f5a46c809cee98e7514127327b1cab58080ff018080808080ffff80ff80ff80ff80ff8080808080a18f4f7f0ac07240de1477a4147ca1bf7afd88808fd88aabb0296ddcffd6cd3cee16696c5fad7fed5fa67699a4ec554717b58e15c12a8fcebddc70c52a4cee4c98b7210cfcb5eb2a1d8f75f2575c421474e767efef39e652c0d2ef14f5f433b8",  # noqa
        "taker": [
            {
                "store_id": "7acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3",
                "inclusions": [{"key": "10", "value": "0210"}],
            }
        ],
        "maker": [
            {
                "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
                "proofs": [
                    {
                        "key": "10",
                        "value": "0110",
                        "node_hash": "de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58",
                        "layers": [
                            {
                                "other_hash_side": "left",
                                "other_hash": "1c8ab812b97f5a9da0ba4be2380104810fe5c8022efe9b9e2c9d188fc3537434",
                                "combined_hash": "d340000b3a6717a5a8d42b24516ff69430235c771f8a527554b357b7f03c6de0",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "54e8b4cac761778f396840b343c0f1cb0e1fd0c9927d48d2f0d09a7a6f225126",
                                "combined_hash": "7676004a15439e4e8345d0f9f3a15500805b3447285904b7bcd7d14e27381d2e",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "6a37ca2d9a37a50f2d53387c3cf31395c72d75b1aacfa4402c32dc6d354542b4",
                                "combined_hash": "b1dc97f797a32631483c11d33b4759f5b498b512b7436286d1dc00bb1024b7e2",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "bcff6f16886339a196a2f6c842ad6d350a8579d123eb8602a0a85965ba25d671",
                                "combined_hash": "8e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea",
                            },
                        ],
                    }
                ],
            }
        ],
    },
    maker_inclusions=[{"key": b"\x10".hex(), "value": b"\x01\x10".hex()}],
    taker_inclusions=[{"key": b"\x10".hex(), "value": b"\x02\x10".hex()}],
    trade_id="ecc205b2ffe49b87b2f385f595a395ab13cf0e0627e028a1222a0b4d255bdc18",
    maker_root_history=[
        bytes32.from_hexstr("6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27"),
        bytes32.from_hexstr("8e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea"),
    ],
    taker_root_history=[
        bytes32.from_hexstr("42f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb"),
        bytes32.from_hexstr("eeb63ac765065d2ee161e1c059c8188ef809e1c3ed8739bad5bfee2c2ee1c742"),
    ],
)


make_one_take_one_same_values_reference = MakeAndTakeReference(
    entries_to_insert=10,
    make_offer_response={
        "trade_id": "d2bebdb0ee1fdd4a38f7c8c5a25bf6839794268f955e469818998ad5dad92d4d",
        "offer": "00000003000000000000000000000000000000000000000000000000000000000000000052eba05592a7cbe77b4b1552cacec440b20d523d08a6be917c9213dc34f3033a0000000000000000ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa042f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff018080808080ff01808080ffffa00000000000000000000000000000000000000000000000000000000000000000ffffa00000000000000000000000000000000000000000000000000000000000000000ff01ff80808080ca2e21c90d263e63b73d449a3f8d57b9458846f7af27d9a61a515395fa14071ed15ec60900d04972f30df7bde60487bd63d17889f405398376809fc975e3177c0000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa01d1eb374688e3033cbce2514e4fded10ceffe068e663718b8a20716a65019f9180ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2aff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01d1eb374688e3033cbce2514e4fded10ceffe068e663718b8a20716a65019f91ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2a8080ffff3eff248080ff018080808080ff01808080ffffa032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243ffa08c4aebb18e8ce08405083c3d90a29f30239865142e2dcbca5393f40df9e3821dff0180ff01ffff80808032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243aa064e96a86637d8f5ebe153dc8645d29f43bee762d5ec10d06c8617fa60b8c50000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a132fae32c98cbb7d8f5814c49ee3f0ba6ec2172c5e5f6900655a65cd2157a06a1c6eb89c68c8d2cdcee9506c2217978ff018080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0102ff2bff0580ffff01ff0bffff0102ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff3fffa09502844b542b20256008242b5676246b765d0e4c82714466a1140489e07bf0e880ffff81e8ff0bffffffffa01d1eb374688e3033cbce2514e4fded10ceffe068e663718b8a20716a65019f9180ffa057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a980ff808080ffff33ffa0352ef238e8561d0bfc8f754683b4d23ef9f40f7c4b574e333bb52ec81aa0b868ff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01d1eb374688e3033cbce2514e4fded10ceffe068e663718b8a20716a65019f91ffa0352ef238e8561d0bfc8f754683b4d23ef9f40f7c4b574e333bb52ec81aa0b868808080ffff04ffff01ffffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da980ffff04ffff01ffa0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c280ffff04ffff01ffffa06cae87c81f9edf8516076a9eb56a354ced636998a9f40b278c7bfddfb655df568080ff018080808080ffff80ff80ff80ff80ff8080808080877a8d3055ad9746e85b725221c78616af1a7b223a32be868d7b9135fbb4da0379307fa3073a958782d5db985425974a125117ae957b9074c0ee548bd4dfdd7ed19cbe9974a838383b51e19060ab6c2a7a83f676346125a288a6b6519e7aa148",  # noqa
        "taker": [
            {
                "store_id": "7acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3",
                "inclusions": [{"key": "10", "value": "0510"}],
            }
        ],
        "maker": [
            {
                "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
                "proofs": [
                    {
                        "key": "10",
                        "value": "0510",
                        "node_hash": "6cae87c81f9edf8516076a9eb56a354ced636998a9f40b278c7bfddfb655df56",
                        "layers": [
                            {
                                "other_hash_side": "right",
                                "other_hash": "9e4574191777193c145c7e09eb6394501f81dee6eb1b05f0881bb478828cb9ea",
                                "combined_hash": "fbd72dad09a493adff38e71fb47cf331d4355f2671751392e2b96420cfb7c140",
                            },
                            {
                                "other_hash_side": "left",
                                "other_hash": "9daec46b6819e836d66144119dd084765cfe7ed9ac3222c0c0f64590a4a43b3a",
                                "combined_hash": "7419ef13c946053805fff6d5741bfc770ef901dbf6048ca9b6248c12179c1d6c",
                            },
                            {
                                "other_hash_side": "left",
                                "other_hash": "a624e12b8db06e55dcf520cedf4ff744c3aac35ebeb0b05a0f63bcb41ba8b221",
                                "combined_hash": "c4f1ff4d8f699320060b294a12c71118e5921b3e8e74b3fbdd410b1abe2a114e",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "bcff6f16886339a196a2f6c842ad6d350a8579d123eb8602a0a85965ba25d671",
                                "combined_hash": "1d1eb374688e3033cbce2514e4fded10ceffe068e663718b8a20716a65019f91",
                            },
                        ],
                    }
                ],
            }
        ],
    },
    maker_inclusions=[{"key": b"\x10".hex(), "value": b"\x05\x10".hex()}],
    taker_inclusions=[{"key": b"\x10".hex(), "value": b"\x05\x10".hex()}],
    trade_id="57e31189153fca54e70207c02bf27b8e271fcbfa1fac8076474a9a1cc04d3b63",
    maker_root_history=[
        bytes32.from_hexstr("6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27"),
        bytes32.from_hexstr("1d1eb374688e3033cbce2514e4fded10ceffe068e663718b8a20716a65019f91"),
    ],
    taker_root_history=[
        bytes32.from_hexstr("42f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb"),
        bytes32.from_hexstr("87ebc7585e5b291203c318a7be96ca9cdfd5ddfc9cc2a97f55a3eddb49f0c74e"),
    ],
)


make_two_take_one_reference = MakeAndTakeReference(
    entries_to_insert=10,
    make_offer_response={
        "trade_id": "04ea501a3344c1c4c7aedf50ec2751d69d2ff09bd6caeb1ea529071225f413bc",
        "offer": "00000003000000000000000000000000000000000000000000000000000000000000000052eba05592a7cbe77b4b1552cacec440b20d523d08a6be917c9213dc34f3033a0000000000000000ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa042f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff018080808080ff01808080ffffa00000000000000000000000000000000000000000000000000000000000000000ffffa00000000000000000000000000000000000000000000000000000000000000000ff01ff80808080ca2e21c90d263e63b73d449a3f8d57b9458846f7af27d9a61a515395fa14071e69c05748eab24bce907ef7840c14873f1e668bda10c7aab57e25bb7895a88db20000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa0043fed6d67961e36db2900b6aab24aa68be529c4e632aace486fbea1b26dc70e80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2aff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa0043fed6d67961e36db2900b6aab24aa68be529c4e632aace486fbea1b26dc70effa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2a8080ffff3eff248080ff018080808080ff01808080ffffa032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243ffa08c4aebb18e8ce08405083c3d90a29f30239865142e2dcbca5393f40df9e3821dff0180ff01ffff80808032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243aa064e96a86637d8f5ebe153dc8645d29f43bee762d5ec10d06c8617fa60b8c50000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a132fae32c98cbb7d8f5814c49ee3f0ba6ec2172c5e5f6900655a65cd2157a06a1c6eb89c68c8d2cdcee9506c2217978ff018080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0102ff2bff0580ffff01ff0bffff0102ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff3fffa0890bd0a05cc152c27a3a72348d59e9c5fb46c18da8f32948f1f2143b35014aca80ffff81e8ff0bffffffffa0043fed6d67961e36db2900b6aab24aa68be529c4e632aace486fbea1b26dc70e80ffa057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a980ff808080ffff33ffa09130956ec241f3c4f8807f6889e65025947fbd7bb757d8df0ba2640e293bcc60ff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa0043fed6d67961e36db2900b6aab24aa68be529c4e632aace486fbea1b26dc70effa09130956ec241f3c4f8807f6889e65025947fbd7bb757d8df0ba2640e293bcc60808080ffff04ffff01ffffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da980ffff04ffff01ffa0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c280ffff04ffff01ffffa07f3e180acdf046f955d3440bb3a16dfd6f5a46c809cee98e7514127327b1cab58080ff018080808080ffff80ff80ff80ff80ff8080808080952dd3e68ea36950708547ddc57bea7a97d9e7a2d5c7921be7c72be43abc432406b6b1786e3a52b6a5dc53159409e55703d00eb60ca407a2712a5b637bc3599a0073d7c9a6009c16547f5fae0f8932002d5318fa4f2f4a9f19ab3f7362118230",  # noqa
        "taker": [
            {
                "store_id": "7acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3",
                "inclusions": [{"key": "10", "value": "0210"}],
            }
        ],
        "maker": [
            {
                "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
                "proofs": [
                    {
                        "key": "10",
                        "value": "0110",
                        "node_hash": "de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58",
                        "layers": [
                            {
                                "other_hash_side": "left",
                                "other_hash": "1c8ab812b97f5a9da0ba4be2380104810fe5c8022efe9b9e2c9d188fc3537434",
                                "combined_hash": "d340000b3a6717a5a8d42b24516ff69430235c771f8a527554b357b7f03c6de0",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "54e8b4cac761778f396840b343c0f1cb0e1fd0c9927d48d2f0d09a7a6f225126",
                                "combined_hash": "7676004a15439e4e8345d0f9f3a15500805b3447285904b7bcd7d14e27381d2e",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "e24b5bf6fa30a0fb836b369a471c957afcf8c2c39521f9ffd0b45aa9f172e8b9",
                                "combined_hash": "cf98873e50b9e84485c5b6729b6023e24140a7c019efe06ee594256e8f8bf523",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "bcff6f16886339a196a2f6c842ad6d350a8579d123eb8602a0a85965ba25d671",
                                "combined_hash": "043fed6d67961e36db2900b6aab24aa68be529c4e632aace486fbea1b26dc70e",
                            },
                        ],
                    },
                    {
                        "key": "11",
                        "value": "0111",
                        "node_hash": "e866daa84d1785d1e1e3b228e2fd50031342e7501c08a074965da3d4f5ca4be2",
                        "layers": [
                            {
                                "other_hash_side": "left",
                                "other_hash": "9daec46b6819e836d66144119dd084765cfe7ed9ac3222c0c0f64590a4a43b3a",
                                "combined_hash": "dfa8a2f284a05d6974096f138ec2a66086065ec2fbec7e564b367bb15e81d75d",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "9e4574191777193c145c7e09eb6394501f81dee6eb1b05f0881bb478828cb9ea",
                                "combined_hash": "e24b5bf6fa30a0fb836b369a471c957afcf8c2c39521f9ffd0b45aa9f172e8b9",
                            },
                            {
                                "other_hash_side": "left",
                                "other_hash": "7676004a15439e4e8345d0f9f3a15500805b3447285904b7bcd7d14e27381d2e",
                                "combined_hash": "cf98873e50b9e84485c5b6729b6023e24140a7c019efe06ee594256e8f8bf523",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "bcff6f16886339a196a2f6c842ad6d350a8579d123eb8602a0a85965ba25d671",
                                "combined_hash": "043fed6d67961e36db2900b6aab24aa68be529c4e632aace486fbea1b26dc70e",
                            },
                        ],
                    },
                ],
            }
        ],
    },
    maker_inclusions=[
        {"key": b"\x10".hex(), "value": b"\x01\x10".hex()},
        {"key": b"\x11".hex(), "value": b"\x01\x11".hex()},
    ],
    taker_inclusions=[{"key": b"\x10".hex(), "value": b"\x02\x10".hex()}],
    trade_id="4f5412917a22233fa6186013392144bc469d23576d108b98faa9c7e76d036af4",
    maker_root_history=[
        bytes32.from_hexstr("6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27"),
        bytes32.from_hexstr("043fed6d67961e36db2900b6aab24aa68be529c4e632aace486fbea1b26dc70e"),
    ],
    taker_root_history=[
        bytes32.from_hexstr("42f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb"),
        bytes32.from_hexstr("eeb63ac765065d2ee161e1c059c8188ef809e1c3ed8739bad5bfee2c2ee1c742"),
    ],
)


make_one_take_two_reference = MakeAndTakeReference(
    entries_to_insert=10,
    make_offer_response={
        "trade_id": "fa88e673fd1235efd43c1ef4f2957c88f7dcd0b2cfd5bde54a65d52d148ce670",
        "offer": "00000003000000000000000000000000000000000000000000000000000000000000000052eba05592a7cbe77b4b1552cacec440b20d523d08a6be917c9213dc34f3033a0000000000000000ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa042f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff018080808080ff01808080ffffa00000000000000000000000000000000000000000000000000000000000000000ffffa00000000000000000000000000000000000000000000000000000000000000000ff01ff80808080ca2e21c90d263e63b73d449a3f8d57b9458846f7af27d9a61a515395fa14071ea55bba78c76265b4bac257251b1e89dd13637a7c18e8dcb03e092dfb7eb5a84a0000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2aff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2a8080ffff3eff248080ff018080808080ff01808080ffffa032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243ffa08c4aebb18e8ce08405083c3d90a29f30239865142e2dcbca5393f40df9e3821dff0180ff01ffff80808032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243aa064e96a86637d8f5ebe153dc8645d29f43bee762d5ec10d06c8617fa60b8c50000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a132fae32c98cbb7d8f5814c49ee3f0ba6ec2172c5e5f6900655a65cd2157a06a1c6eb89c68c8d2cdcee9506c2217978ff018080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0102ff2bff0580ffff01ff0bffff0102ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff3fffa0bd7aa54c5f93ef1738439aa60b471ce2aa4c62fb18a7943aa10061f00dbdb83680ffff81e8ff0bffffffffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffa057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a980ff808080ffff33ffa0ca77e42ac3b3375edc54af271f21d075afd02d72969cababeec63e22f7ab10deff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0ca77e42ac3b3375edc54af271f21d075afd02d72969cababeec63e22f7ab10de808080ffff04ffff01ffffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da980ffff04ffff01ffa0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c280ffff04ffff01ffffa07f3e180acdf046f955d3440bb3a16dfd6f5a46c809cee98e7514127327b1cab5ffa05eadd0f5982411ec074786cb6e2e37880d2ea1f007b47bc50a1b36cc2c61ba098080ff018080808080ffff80ff80ff80ff80ff808080808097ff2e118c10f392eb2e53be370c1a9226862b59ab0dca4e1751b2196cfdc301f71fddd152d1324e7f3d32800df7c5af14cd0e4ad5389bea2a0f10330916fc29d2debf7d8ab4c3ac496b5d301de36ebb7973888443e13244c68246e54377b775",  # noqa
        "taker": [
            {
                "store_id": "7acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3",
                "inclusions": [{"key": "10", "value": "0210"}, {"key": "11", "value": "0211"}],
            }
        ],
        "maker": [
            {
                "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
                "proofs": [
                    {
                        "key": "10",
                        "value": "0110",
                        "node_hash": "de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58",
                        "layers": [
                            {
                                "other_hash_side": "left",
                                "other_hash": "1c8ab812b97f5a9da0ba4be2380104810fe5c8022efe9b9e2c9d188fc3537434",
                                "combined_hash": "d340000b3a6717a5a8d42b24516ff69430235c771f8a527554b357b7f03c6de0",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "54e8b4cac761778f396840b343c0f1cb0e1fd0c9927d48d2f0d09a7a6f225126",
                                "combined_hash": "7676004a15439e4e8345d0f9f3a15500805b3447285904b7bcd7d14e27381d2e",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "6a37ca2d9a37a50f2d53387c3cf31395c72d75b1aacfa4402c32dc6d354542b4",
                                "combined_hash": "b1dc97f797a32631483c11d33b4759f5b498b512b7436286d1dc00bb1024b7e2",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "bcff6f16886339a196a2f6c842ad6d350a8579d123eb8602a0a85965ba25d671",
                                "combined_hash": "8e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea",
                            },
                        ],
                    }
                ],
            }
        ],
    },
    maker_inclusions=[{"key": b"\x10".hex(), "value": b"\x01\x10".hex()}],
    taker_inclusions=[
        {"key": b"\x10".hex(), "value": b"\x02\x10".hex()},
        {"key": b"\x11".hex(), "value": b"\x02\x11".hex()},
    ],
    trade_id="48efd113518a57895d45f5cde246d9e088e08d96a562e6013eb4c04527e4d5ba",
    maker_root_history=[
        bytes32.from_hexstr("6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27"),
        bytes32.from_hexstr("8e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea"),
    ],
    taker_root_history=[
        bytes32.from_hexstr("42f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb"),
        bytes32.from_hexstr("2215da3c9a309e0d8972fd6acb8ac62898a0f7e4a07351d558c2cc5094dfc5ec"),
    ],
)


make_one_existing_take_one_reference = MakeAndTakeReference(
    entries_to_insert=10,
    make_offer_response={
        "trade_id": "1efc47397715da444017864d15b92676bc416afcb7aba14047c6edfd6f4fa766",
        "offer": "00000003000000000000000000000000000000000000000000000000000000000000000052eba05592a7cbe77b4b1552cacec440b20d523d08a6be917c9213dc34f3033a0000000000000000ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa042f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff018080808080ff01808080ffffa00000000000000000000000000000000000000000000000000000000000000000ffffa00000000000000000000000000000000000000000000000000000000000000000ff01ff80808080ca2e21c90d263e63b73d449a3f8d57b9458846f7af27d9a61a515395fa14071ef1932b0458af07a67925e9e0d5eca3ae137ba72bc689bd9b7b00bd0508ee6be80000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2aff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2a8080ffff3eff248080ff018080808080ff01808080ffffa032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243ffa08c4aebb18e8ce08405083c3d90a29f30239865142e2dcbca5393f40df9e3821dff0180ff01ffff80808032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243aa064e96a86637d8f5ebe153dc8645d29f43bee762d5ec10d06c8617fa60b8c50000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a132fae32c98cbb7d8f5814c49ee3f0ba6ec2172c5e5f6900655a65cd2157a06a1c6eb89c68c8d2cdcee9506c2217978ff018080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0102ff2bff0580ffff01ff0bffff0102ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff3fffa06766ecb6a87bcab8829fc9b3f08c8b5a83ecb7c5597c6a13ec346bfcafc1aab880ffff33ffa09b077471a29fd048bf897998e3f73ee5215345cd4943441e7c654dc11f2c579eff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27ffa09b077471a29fd048bf897998e3f73ee5215345cd4943441e7c654dc11f2c579e808080ffff04ffff01ffffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da980ffff04ffff01ffa0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c280ffff04ffff01ffffa07f3e180acdf046f955d3440bb3a16dfd6f5a46c809cee98e7514127327b1cab58080ff018080808080ffff80ff80ff80ff80ff80808080809200d622b5462e5c56846dfbf374090fe9afef15ade6b26cac913dce6005df00550a26f624807adb98240ea731fa37d2054f37d4f2feb416b110c4cdf190ed5393e059c871b7e56897bf65aa4c1b95b31d2f16e41600d8f74372ee41cc11b39b",  # noqa
        "taker": [
            {
                "store_id": "7acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3",
                "inclusions": [{"key": "10", "value": "0210"}],
            }
        ],
        "maker": [
            {
                "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
                "proofs": [
                    {
                        "key": "09",
                        "value": "0109",
                        "node_hash": "0ab4218d9b9763bb4978723b6bc3dcde8a952c49d6d6bbdebf9753e33ae94a4d",
                        "layers": [
                            {
                                "other_hash_side": "right",
                                "other_hash": "a9f71348ec8cf151e38fe0f6aa841dff3eac1f5a34161147e700ca179d2f7189",
                                "combined_hash": "577ab817898afbd1e149b8933322226fcd1e38f4c3921e7700dddae8c886996d",
                            },
                            {
                                "other_hash_side": "left",
                                "other_hash": "0e81e890b50e4547357938fb9cb81c7f17178e3f1bc47b784cd139ef9707c045",
                                "combined_hash": "f6a103cb21324e62dd5ca99eac6649b33be36af0b22588801c51196b571713ff",
                            },
                            {
                                "other_hash_side": "left",
                                "other_hash": "b2586f6b7a4a76e99064549f324d53c7f60eb2d5f67bd0c24444d0167dc7dc01",
                                "combined_hash": "2a6b820ed0e775d7f2e88fbbac8908f09880ca75a6f7e0f8611c940ee2dc8cec",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "ff63e1ccbbd40190042ed1ed2b553e264828065d1bb7fd3fe479d4444223e043",
                                "combined_hash": "bcff6f16886339a196a2f6c842ad6d350a8579d123eb8602a0a85965ba25d671",
                            },
                            {
                                "other_hash_side": "left",
                                "other_hash": "980a121e80381e79b37aa634758ff8a56c6cdf67c50ec0e75d14b4749dcde189",
                                "combined_hash": "6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27",
                            },
                        ],
                    }
                ],
            }
        ],
    },
    maker_inclusions=[{"key": b"\x09".hex(), "value": b"\x01\x09".hex()}],
    taker_inclusions=[{"key": b"\x10".hex(), "value": b"\x02\x10".hex()}],
    trade_id="faea189031da8557299173e6731dafea53d85e116485ffaa8ff2070278145608",
    maker_root_history=[
        bytes32.from_hexstr("6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27"),
    ],
    taker_root_history=[
        bytes32.from_hexstr("42f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb"),
        bytes32.from_hexstr("eeb63ac765065d2ee161e1c059c8188ef809e1c3ed8739bad5bfee2c2ee1c742"),
    ],
)


make_one_take_one_existing_reference = MakeAndTakeReference(
    entries_to_insert=10,
    make_offer_response={
        "trade_id": "b8576f50159e5e9eae5de00b8986084705f0796317d5da8cd0e968f2c1a7893e",
        "offer": "00000003000000000000000000000000000000000000000000000000000000000000000052eba05592a7cbe77b4b1552cacec440b20d523d08a6be917c9213dc34f3033a0000000000000000ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa042f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff018080808080ff01808080ffffa00000000000000000000000000000000000000000000000000000000000000000ffffa00000000000000000000000000000000000000000000000000000000000000000ff01ff80808080ca2e21c90d263e63b73d449a3f8d57b9458846f7af27d9a61a515395fa14071ea55bba78c76265b4bac257251b1e89dd13637a7c18e8dcb03e092dfb7eb5a84a0000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2aff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2a8080ffff3eff248080ff018080808080ff01808080ffffa032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243ffa08c4aebb18e8ce08405083c3d90a29f30239865142e2dcbca5393f40df9e3821dff0180ff01ffff80808032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243aa064e96a86637d8f5ebe153dc8645d29f43bee762d5ec10d06c8617fa60b8c50000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a132fae32c98cbb7d8f5814c49ee3f0ba6ec2172c5e5f6900655a65cd2157a06a1c6eb89c68c8d2cdcee9506c2217978ff018080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0102ff2bff0580ffff01ff0bffff0102ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff3fffa0bd7aa54c5f93ef1738439aa60b471ce2aa4c62fb18a7943aa10061f00dbdb83680ffff81e8ff0bffffffffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffa057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a980ff808080ffff33ffa0ca77e42ac3b3375edc54af271f21d075afd02d72969cababeec63e22f7ab10deff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0ca77e42ac3b3375edc54af271f21d075afd02d72969cababeec63e22f7ab10de808080ffff04ffff01ffffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da980ffff04ffff01ffa0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c280ffff04ffff01ffffa09dd8b0a6d67ee56221d0fe6bb131eb30d17c098c7548a78a962836011ea465bb8080ff018080808080ffff80ff80ff80ff80ff8080808080a01626555f71b404f754061c4de0143b82248008fd1920466eee86ce447db889cf4287b8363a4e0bfdb628decddf19ea074c313ca4ce097f61ba67120e319481ccacbd1adcff2d1d95b859ff516691bca16e2614a56cbd3c1f1ec5580da269ab",  # noqa
        "taker": [
            {
                "store_id": "7acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3",
                "inclusions": [{"key": "09", "value": "0209"}],
            }
        ],
        "maker": [
            {
                "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
                "proofs": [
                    {
                        "key": "10",
                        "value": "0110",
                        "node_hash": "de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58",
                        "layers": [
                            {
                                "other_hash_side": "left",
                                "other_hash": "1c8ab812b97f5a9da0ba4be2380104810fe5c8022efe9b9e2c9d188fc3537434",
                                "combined_hash": "d340000b3a6717a5a8d42b24516ff69430235c771f8a527554b357b7f03c6de0",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "54e8b4cac761778f396840b343c0f1cb0e1fd0c9927d48d2f0d09a7a6f225126",
                                "combined_hash": "7676004a15439e4e8345d0f9f3a15500805b3447285904b7bcd7d14e27381d2e",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "6a37ca2d9a37a50f2d53387c3cf31395c72d75b1aacfa4402c32dc6d354542b4",
                                "combined_hash": "b1dc97f797a32631483c11d33b4759f5b498b512b7436286d1dc00bb1024b7e2",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "bcff6f16886339a196a2f6c842ad6d350a8579d123eb8602a0a85965ba25d671",
                                "combined_hash": "8e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea",
                            },
                        ],
                    }
                ],
            }
        ],
    },
    maker_inclusions=[{"key": b"\x10".hex(), "value": b"\x01\x10".hex()}],
    taker_inclusions=[{"key": b"\x09".hex(), "value": b"\x02\x09".hex()}],
    trade_id="c390d8ff22ae5c6fe4559a01f713703aa023e6b8f2e89ec4340da5237d4d9c95",
    maker_root_history=[
        bytes32.from_hexstr("6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27"),
        bytes32.from_hexstr("8e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea"),
    ],
    taker_root_history=[
        bytes32.from_hexstr("42f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb"),
    ],
)


make_one_upsert_take_one_reference = MakeAndTakeReference(
    entries_to_insert=10,
    make_offer_response={
        "trade_id": "99cac76f3180c06126087b1188f3a5cd6a5f5f2830ff639e7fca9e11afe2b477",
        "offer": "00000003000000000000000000000000000000000000000000000000000000000000000052eba05592a7cbe77b4b1552cacec440b20d523d08a6be917c9213dc34f3033a0000000000000000ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa042f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff018080808080ff01808080ffffa00000000000000000000000000000000000000000000000000000000000000000ffffa00000000000000000000000000000000000000000000000000000000000000000ff01ff80808080ca2e21c90d263e63b73d449a3f8d57b9458846f7af27d9a61a515395fa14071e3a306420fb91e6a9c25cb93938b5c9e164ce761abc2ab967f8545cdcdc9e6e6d0000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa03761921b9b0520458995bb0ec353ea28d36efa2a7cfc3aba6772f005f7dd34c680ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2aff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa03761921b9b0520458995bb0ec353ea28d36efa2a7cfc3aba6772f005f7dd34c6ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2a8080ffff3eff248080ff018080808080ff01808080ffffa032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243ffa08c4aebb18e8ce08405083c3d90a29f30239865142e2dcbca5393f40df9e3821dff0180ff01ffff80808032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243aa064e96a86637d8f5ebe153dc8645d29f43bee762d5ec10d06c8617fa60b8c50000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a132fae32c98cbb7d8f5814c49ee3f0ba6ec2172c5e5f6900655a65cd2157a06a1c6eb89c68c8d2cdcee9506c2217978ff018080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0102ff2bff0580ffff01ff0bffff0102ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff3fffa0214dc115c3f3a3444619449b297fe03521f85c8cc12be80d8de35bb9cfb29e6d80ffff81e8ff0bffffffffa03761921b9b0520458995bb0ec353ea28d36efa2a7cfc3aba6772f005f7dd34c680ffa057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a980ff808080ffff33ffa05ef937e981ce68f2fa71e00b139acb3352b5ec32e7d6bc160874a456f106016cff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa03761921b9b0520458995bb0ec353ea28d36efa2a7cfc3aba6772f005f7dd34c6ffa05ef937e981ce68f2fa71e00b139acb3352b5ec32e7d6bc160874a456f106016c808080ffff04ffff01ffffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da980ffff04ffff01ffa0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c280ffff04ffff01ffffa07f3e180acdf046f955d3440bb3a16dfd6f5a46c809cee98e7514127327b1cab58080ff018080808080ffff80ff80ff80ff80ff8080808080a389748450bfea49b130c33fd987561f90eef2ffb8d5aac36590fa1d724f5d8bc0b86f23f0538b35922a098427a5afee0280ed240c03fcd9d736c7e752152f4387a023222ba5711c05417f369aeda2827cef78793acfd79dd7960c80932ccc89",  # noqa
        "taker": [
            {
                "store_id": "7acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3",
                "inclusions": [{"key": "10", "value": "0210"}],
            }
        ],
        "maker": [
            {
                "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
                "proofs": [
                    {
                        "key": "09",
                        "value": "0110",
                        "node_hash": "537527cd8d1ba52f94be6adde14400becd977f0a8cdcee17b10e74d408a64af8",
                        "layers": [
                            {
                                "other_hash_side": "right",
                                "other_hash": "1c8ab812b97f5a9da0ba4be2380104810fe5c8022efe9b9e2c9d188fc3537434",
                                "combined_hash": "a642d1018f3ff35a6f693407cb9860cfb7a8f969d356e7dda0ef8c89a61060b7",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "54e8b4cac761778f396840b343c0f1cb0e1fd0c9927d48d2f0d09a7a6f225126",
                                "combined_hash": "d1d6e6f1f4e5d776405fbf98872075c3434462ebf8d139880f28dd6e42aece90",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "6a37ca2d9a37a50f2d53387c3cf31395c72d75b1aacfa4402c32dc6d354542b4",
                                "combined_hash": "80f288f1fb9feafaa53de8b54622ef2f2532aa6422081ac143540c36d9a2bde2",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "ca35e1f8ddc62f809f8b4c44a965273eb88cb720add4ba4b03c9865b70ef18a2",
                                "combined_hash": "3761921b9b0520458995bb0ec353ea28d36efa2a7cfc3aba6772f005f7dd34c6",
                            },
                        ],
                    }
                ],
            }
        ],
    },
    maker_inclusions=[{"key": b"\x09".hex(), "value": b"\x01\x10".hex()}],
    taker_inclusions=[{"key": b"\x10".hex(), "value": b"\x02\x10".hex()}],
    trade_id="25651c321494cee55394b73a69d638df34026d999887a88b154696880231df72",
    maker_root_history=[
        bytes32.from_hexstr("6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27"),
        bytes32.from_hexstr("3761921b9b0520458995bb0ec353ea28d36efa2a7cfc3aba6772f005f7dd34c6"),
    ],
    taker_root_history=[
        bytes32.from_hexstr("42f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb"),
        bytes32.from_hexstr("eeb63ac765065d2ee161e1c059c8188ef809e1c3ed8739bad5bfee2c2ee1c742"),
    ],
)


make_one_take_one_upsert_reference = MakeAndTakeReference(
    entries_to_insert=10,
    make_offer_response={
        "trade_id": "d9d985e9bc941df8f5718f31b597a061e99fb39d430def2b3d8bc289b0b1020e",
        "offer": "00000003000000000000000000000000000000000000000000000000000000000000000052eba05592a7cbe77b4b1552cacec440b20d523d08a6be917c9213dc34f3033a0000000000000000ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa042f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff018080808080ff01808080ffffa00000000000000000000000000000000000000000000000000000000000000000ffffa00000000000000000000000000000000000000000000000000000000000000000ff01ff80808080ca2e21c90d263e63b73d449a3f8d57b9458846f7af27d9a61a515395fa14071ea55bba78c76265b4bac257251b1e89dd13637a7c18e8dcb03e092dfb7eb5a84a0000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2aff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0c842b1a384b8633ac25d0f12bd7b614f86a77642ab6426418750f2b0b86bab2a8080ffff3eff248080ff018080808080ff01808080ffffa032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243ffa08c4aebb18e8ce08405083c3d90a29f30239865142e2dcbca5393f40df9e3821dff0180ff01ffff80808032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa243aa064e96a86637d8f5ebe153dc8645d29f43bee762d5ec10d06c8617fa60b8c50000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa06661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e2780ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a132fae32c98cbb7d8f5814c49ee3f0ba6ec2172c5e5f6900655a65cd2157a06a1c6eb89c68c8d2cdcee9506c2217978ff018080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0102ff2bff0580ffff01ff0bffff0102ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff3fffa0bd7aa54c5f93ef1738439aa60b471ce2aa4c62fb18a7943aa10061f00dbdb83680ffff81e8ff0bffffffffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea80ffa057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a980ff808080ffff33ffa0ca77e42ac3b3375edc54af271f21d075afd02d72969cababeec63e22f7ab10deff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa08e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65eaffa0ca77e42ac3b3375edc54af271f21d075afd02d72969cababeec63e22f7ab10de808080ffff04ffff01ffffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da980ffff04ffff01ffa0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c280ffff04ffff01ffffa05743f9c9e6f3ebd1506342bbf0a6bfb9dc68b58b3e7f6f32da759fb0fb74fe0e8080ff018080808080ffff80ff80ff80ff80ff8080808080a7db721cb3da800e516ac87dace73404ad29cf68377a3af155e1ee1205dc34c07cefdbef7e3a9de7bf492a840c74883c039698b68f2d4d42062f5a2fd8c99da29226771305720f305cde56c417d0c5de53a9322fd3cedc4150d42540863edeaa",  # noqa
        "taker": [
            {
                "store_id": "7acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3",
                "inclusions": [{"key": "09", "value": "0210"}],
            }
        ],
        "maker": [
            {
                "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
                "proofs": [
                    {
                        "key": "10",
                        "value": "0110",
                        "node_hash": "de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58",
                        "layers": [
                            {
                                "other_hash_side": "left",
                                "other_hash": "1c8ab812b97f5a9da0ba4be2380104810fe5c8022efe9b9e2c9d188fc3537434",
                                "combined_hash": "d340000b3a6717a5a8d42b24516ff69430235c771f8a527554b357b7f03c6de0",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "54e8b4cac761778f396840b343c0f1cb0e1fd0c9927d48d2f0d09a7a6f225126",
                                "combined_hash": "7676004a15439e4e8345d0f9f3a15500805b3447285904b7bcd7d14e27381d2e",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "6a37ca2d9a37a50f2d53387c3cf31395c72d75b1aacfa4402c32dc6d354542b4",
                                "combined_hash": "b1dc97f797a32631483c11d33b4759f5b498b512b7436286d1dc00bb1024b7e2",
                            },
                            {
                                "other_hash_side": "right",
                                "other_hash": "bcff6f16886339a196a2f6c842ad6d350a8579d123eb8602a0a85965ba25d671",
                                "combined_hash": "8e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea",
                            },
                        ],
                    }
                ],
            }
        ],
    },
    maker_inclusions=[{"key": b"\x10".hex(), "value": b"\x01\x10".hex()}],
    taker_inclusions=[{"key": b"\x09".hex(), "value": b"\x02\x10".hex()}],
    trade_id="515ecf094f1a4439faa9d64b8101b68df01536588ebbc9970c41c3f11ad0d602",
    maker_root_history=[
        bytes32.from_hexstr("6661ea6604b491118b0f49c932c0f0de2ad815a57b54b6ec8fdbd1b408ae7e27"),
        bytes32.from_hexstr("8e54f5066aa7999fc1561a56df59d11ff01f7df93cadf49a61adebf65dec65ea"),
    ],
    taker_root_history=[
        bytes32.from_hexstr("42f08ebc0578f2cec7a9ad1c3038e74e0f30eba5c2f4cb1ee1c8fdb682c19dbb"),
        bytes32.from_hexstr("d77afd64e9f307f3250a352c155480311512f9da2033228f1a2f0a3687cc90e0"),
    ],
)


make_one_take_one_unpopulated_reference = MakeAndTakeReference(
    entries_to_insert=0,
    make_offer_response={
        "trade_id": "120a94680f0cff61cdf3b123260a98253649a2b9762b7d2dead60caad96276e4",
        "offer": "000000030000000000000000000000000000000000000000000000000000000000000000785bba8a904677219cb83f053b1bcf3b5ed13d35895c5babb007c67727e743590000000000000000ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa0000000000000000000000000000000000000000000000000000000000000000080ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ff0affff04ff02ffff04ff03ff80808080ffff04ffff01ffff333effff02ffff03ff05ffff01ff04ffff04ff0cffff04ffff02ff1effff04ff02ffff04ff09ff80808080ff808080ffff02ff16ffff04ff02ffff04ff19ffff04ffff02ff0affff04ff02ffff04ff0dff80808080ff808080808080ff8080ff0180ffff02ffff03ff05ffff01ff02ffff03ffff15ff29ff8080ffff01ff04ffff04ff08ff0980ffff02ff16ffff04ff02ffff04ff0dffff04ff0bff808080808080ffff01ff088080ff0180ffff010b80ff0180ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff1effff04ff02ffff04ff09ff80808080ffff02ff1effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ff018080808080ff01808080ffffa00000000000000000000000000000000000000000000000000000000000000000ffffa00000000000000000000000000000000000000000000000000000000000000000ff01ff8080808032dbe6d545f24635c7871ea53c623c358d7cea8f5e27a983ba6e5c0bf35fa24386ab01fbd8342f8e1dac10d6e906cef3892857bd1865b6fd7ed4b01b39d568b50000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa0de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c5880ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff01ffff33ffa0846b58db3bd246785e202eeddfbb46acaf267f011307437cd4e0841f3da751f6ff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa0de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58ffa0846b58db3bd246785e202eeddfbb46acaf267f011307437cd4e0841f3da751f68080ffff3eff248080ff018080808080ff01808080ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa01804338c97f989c78d88716206c0f27315f3eb7d59417ab2eacee20f0a7ff60bff0180ff01ffff808080a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa478416871446884ef363bd105960c464b4208a293b348f0f1c2e12140df38469450000000000000001ff02ffff01ff02ffff01ff02ffff03ffff18ff2fff3480ffff01ff04ffff04ff20ffff04ff2fff808080ffff04ffff02ff3effff04ff02ffff04ff05ffff04ffff02ff2affff04ff02ffff04ff27ffff04ffff02ffff03ff77ffff01ff02ff36ffff04ff02ffff04ff09ffff04ff57ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ffff011d80ff0180ffff04ffff02ffff03ff77ffff0181b7ffff015780ff0180ff808080808080ffff04ff77ff808080808080ffff02ff3affff04ff02ffff04ff05ffff04ffff02ff0bff5f80ffff01ff8080808080808080ffff01ff088080ff0180ffff04ffff01ffffffff4947ff0233ffff0401ff0102ffffff20ff02ffff03ff05ffff01ff02ff32ffff04ff02ffff04ff0dffff04ffff0bff3cffff0bff34ff2480ffff0bff3cffff0bff3cffff0bff34ff2c80ff0980ffff0bff3cff0bffff0bff34ff8080808080ff8080808080ffff010b80ff0180ffff02ffff03ffff22ffff09ffff0dff0580ff2280ffff09ffff0dff0b80ff2280ffff15ff17ffff0181ff8080ffff01ff0bff05ff0bff1780ffff01ff088080ff0180ff02ffff03ff0bffff01ff02ffff03ffff02ff26ffff04ff02ffff04ff13ff80808080ffff01ff02ffff03ffff20ff1780ffff01ff02ffff03ffff09ff81b3ffff01818f80ffff01ff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff808080808080ffff01ff04ffff04ff23ffff04ffff02ff36ffff04ff02ffff04ff09ffff04ff53ffff04ffff02ff2effff04ff02ffff04ff05ff80808080ff808080808080ff738080ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff34ff8080808080808080ff0180ffff01ff088080ff0180ffff01ff04ff13ffff02ff3affff04ff02ffff04ff05ffff04ff1bffff04ff17ff8080808080808080ff0180ffff01ff02ffff03ff17ff80ffff01ff088080ff018080ff0180ffffff02ffff03ffff09ff09ff3880ffff01ff02ffff03ffff18ff2dffff010180ffff01ff0101ff8080ff0180ff8080ff0180ff0bff3cffff0bff34ff2880ffff0bff3cffff0bff3cffff0bff34ff2c80ff0580ffff0bff3cffff02ff32ffff04ff02ffff04ff07ffff04ffff0bff34ff3480ff8080808080ffff0bff34ff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ffff21ff17ffff09ff0bff158080ffff01ff04ff30ffff04ff0bff808080ffff01ff088080ff0180ff018080ffff04ffff01ffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9ffff04ffff01ff02ffff01ff02ffff01ff02ff3effff04ff02ffff04ff05ffff04ffff02ff2fff5f80ffff04ff80ffff04ffff04ffff04ff0bffff04ff17ff808080ffff01ff808080ffff01ff8080808080808080ffff04ffff01ffffff0233ff04ff0101ffff02ff02ffff03ff05ffff01ff02ff1affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ffff0bff12ffff0bff2cff1080ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff1affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ffff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff2effff04ff02ffff04ff09ff80808080ffff02ff2effff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff02ffff03ff0bffff01ff02ffff03ffff09ff23ff1880ffff01ff02ffff03ffff18ff81b3ff2c80ffff01ff02ffff03ffff20ff1780ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff33ffff04ff2fffff04ff5fff8080808080808080ffff01ff088080ff0180ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff0180ffff01ff02ffff03ffff09ff23ffff0181e880ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ffff02ffff03ffff22ffff09ffff02ff2effff04ff02ffff04ff53ff80808080ff82014f80ffff20ff5f8080ffff01ff02ff53ffff04ff818fffff04ff82014fffff04ff81b3ff8080808080ffff01ff088080ff0180ffff04ff2cff8080808080808080ffff01ff04ff13ffff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff17ffff04ff2fffff04ff5fff80808080808080808080ff018080ff0180ffff01ff04ffff04ff18ffff04ffff02ff16ffff04ff02ffff04ff05ffff04ff27ffff04ffff0bff2cff82014f80ffff04ffff02ff2effff04ff02ffff04ff818fff80808080ffff04ffff0bff2cff0580ff8080808080808080ff378080ff81af8080ff0180ff018080ffff04ffff01a0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c2ffff04ffff01ffa0000000000000000000000000000000000000000000000000000000000000000080ffff04ffff01a057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a9ffff04ffff01ff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b0a3b0219722055ac0a66cd9de5cd3e86962d8c8ec6abb801b57e5c77ed98453b02ceae0e19548f6d4fc20b3a2ec82aa90ff018080ff018080808080ff01808080ffffa09563629e653a9fc3c65f55947883a47e062e6b67394091228ec01352ff78f333ff0180ff01ffffff80ffff02ffff01ff02ffff01ff02ffff03ff5fffff01ff02ff3affff04ff02ffff04ff0bffff04ff17ffff04ff2fffff04ff5fffff04ff81bfffff04ff82017fffff04ff8202ffffff04ffff02ff05ff8205ff80ff8080808080808080808080ffff01ff04ffff04ff10ffff01ff81ff8080ffff02ff05ff8205ff808080ff0180ffff04ffff01ffffff49ff3f02ff04ff0101ffff02ffff02ffff03ff05ffff01ff02ff2affff04ff02ffff04ff0dffff04ffff0bff12ffff0bff2cff1480ffff0bff12ffff0bff12ffff0bff2cff3c80ff0980ffff0bff12ff0bffff0bff2cff8080808080ff8080808080ffff010b80ff0180ff02ffff03ff05ffff01ff02ffff03ffff02ff3effff04ff02ffff04ff82011fffff04ff27ffff04ff4fff808080808080ffff01ff02ff3affff04ff02ffff04ff0dffff04ff1bffff04ff37ffff04ff6fffff04ff81dfffff04ff8201bfffff04ff82037fffff04ffff04ffff04ff28ffff04ffff0bffff02ff26ffff04ff02ffff04ff11ffff04ffff02ff26ffff04ff02ffff04ff13ffff04ff82027fffff04ffff02ff36ffff04ff02ffff04ff82013fff80808080ffff04ffff02ff36ffff04ff02ffff04ff819fff80808080ffff04ffff02ff36ffff04ff02ffff04ff13ff80808080ff8080808080808080ffff04ffff02ff36ffff04ff02ffff04ff09ff80808080ff808080808080ffff012480ff808080ff8202ff80ff8080808080808080808080ffff01ff088080ff0180ffff018202ff80ff0180ffffff0bff12ffff0bff2cff3880ffff0bff12ffff0bff12ffff0bff2cff3c80ff0580ffff0bff12ffff02ff2affff04ff02ffff04ff07ffff04ffff0bff2cff2c80ff8080808080ffff0bff2cff8080808080ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff36ffff04ff02ffff04ff09ff80808080ffff02ff36ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ffff02ffff03ff1bffff01ff02ff2effff04ff02ffff04ffff02ffff03ffff18ffff0101ff1380ffff01ff0bffff0102ff2bff0580ffff01ff0bffff0102ff05ff2b8080ff0180ffff04ffff04ffff17ff13ffff0181ff80ff3b80ff8080808080ffff010580ff0180ff02ffff03ff17ffff01ff02ffff03ffff09ff05ffff02ff2effff04ff02ffff04ff13ffff04ff27ff808080808080ffff01ff02ff3effff04ff02ffff04ff05ffff04ff1bffff04ff37ff808080808080ffff01ff088080ff0180ffff01ff010180ff0180ff018080ffff04ffff01ff01ffff3fffa0fccf087e5b81be2137cfaa35e65cc4e4a25183108907dad33c6d622e8e78349e80ffff81e8ff0bffffffffa0de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c5880ffa057bfd1cb0adda3d94315053fda723f2028320faa8338225d99f629e3d46d43a980ff808080ffff33ffa0b6565d3afb87a60cfdf66bc56cca80b14afc2be649971c8df647ce617b442e6eff01ffffa0a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47ffa0de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58ffa0b6565d3afb87a60cfdf66bc56cca80b14afc2be649971c8df647ce617b442e6e808080ffff04ffff01ffffa07faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9fffa07acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3a0eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da980ffff04ffff01ffa0a04d9f57764f54a43e4030befb4d80026e870519aaa66334aef8304f5d0393c280ffff04ffff01ffffa07f3e180acdf046f955d3440bb3a16dfd6f5a46c809cee98e7514127327b1cab58080ff018080808080ffff80ff80ff80ff80ff808080808090ce896a92f47ab8adec0d7e977795762d85660495f2a6a0c025aec987faac7ec2bd78c17fdcfe126c35fb52ebe75c610df4013ecc5036e95168aba697678d89ab7718664439302d32f1eb85bf263461855c7f3da9050ba7c8da4abb01321836",  # noqa
        "taker": [
            {
                "store_id": "7acfcbd1ed73bfe2b698508f4ea5ed353c60ace154360272ce91f9ab0c8423c3",
                "inclusions": [{"key": "10", "value": "0210"}],
            }
        ],
        "maker": [
            {
                "store_id": "a14daf55d41ced6419bcd011fbc1f74ab9567fe55340d88435aa6493d628fa47",
                "proofs": [
                    {
                        "key": "10",
                        "value": "0110",
                        "node_hash": "de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58",
                        "layers": [],
                    }
                ],
            }
        ],
    },
    maker_inclusions=[{"key": b"\x10".hex(), "value": b"\x01\x10".hex()}],
    taker_inclusions=[{"key": b"\x10".hex(), "value": b"\x02\x10".hex()}],
    trade_id="2dc357c29da4362c6c63dbad128086062d53180395ae86b485dd429ce3791c37",
    maker_root_history=[bytes32.from_hexstr("de4ec93c032f5117d8af076dfc86faa5987a6c0b1d52ffc9cf0dfa43989d8c58")],
    taker_root_history=[bytes32.from_hexstr("7f3e180acdf046f955d3440bb3a16dfd6f5a46c809cee98e7514127327b1cab5")],
)


@pytest.mark.parametrize(
    "reference, offer_setup",
    [
        pytest.param(make_one_take_one_reference, (True, True), id="one for one new/new batch_update"),
        pytest.param(make_one_take_one_reference, (True, False), id="one for one new/old batch_update"),
        pytest.param(make_one_take_one_reference, (False, True), id="one for one old/new batch_update"),
        pytest.param(make_one_take_one_reference, (False, False), id="one for one old/old batch_update"),
        pytest.param(make_one_take_one_same_values_reference, (True, True), id="one for one same values"),
        pytest.param(make_two_take_one_reference, (True, True), id="two for one"),
        pytest.param(make_one_take_two_reference, (True, True), id="one for two"),
        pytest.param(make_one_existing_take_one_reference, (True, True), id="one existing for one"),
        pytest.param(make_one_take_one_existing_reference, (True, True), id="one for one existing"),
        pytest.param(make_one_upsert_take_one_reference, (True, True), id="one upsert for one"),
        pytest.param(make_one_take_one_upsert_reference, (True, True), id="one for one upsert"),
        pytest.param(make_one_take_one_unpopulated_reference, (True, True), id="one for one unpopulated"),
    ],
    indirect=["offer_setup"],
)
@pytest.mark.anyio
async def test_make_and_take_offer(offer_setup: OfferSetup, reference: MakeAndTakeReference) -> None:
    offer_setup = await populate_offer_setup(offer_setup=offer_setup, count=reference.entries_to_insert)

    maker_request = {
        "maker": [
            {
                "store_id": offer_setup.maker.id.hex(),
                "inclusions": reference.maker_inclusions,
            }
        ],
        "taker": [
            {
                "store_id": offer_setup.taker.id.hex(),
                "inclusions": reference.taker_inclusions,
            }
        ],
        "fee": 0,
    }
    maker_response = await offer_setup.maker.api.make_offer(request=maker_request)
    # print(f"\nmaybe_reference_offer = {maker_response['offer']}")

    # only check for success
    # due to differences in chain progression, the exact offer and trade id may differ from the reference
    # assert maker_response == {"success": True, "offer": reference.make_offer_response}
    assert maker_response["success"] is True

    taker_request = {
        "offer": maker_response["offer"],
        "fee": 0,
    }
    taker_response = await offer_setup.taker.api.take_offer(request=taker_request)

    # only check for success
    # due to differences in chain progression, the exact offer and trade id may differ from the reference
    # assert taker_response == {"success": True, "trade_id": reference.trade_id,}
    assert taker_response["success"] is True

    await process_for_data_layer_keys(
        expected_key=hexstr_to_bytes(reference.maker_inclusions[0]["key"]),
        expected_value=hexstr_to_bytes(reference.maker_inclusions[0]["value"]),
        full_node_api=offer_setup.full_node_api,
        data_layer=offer_setup.maker.data_layer,
        store_id=offer_setup.maker.id,
    )
    await process_for_data_layer_keys(
        expected_key=hexstr_to_bytes(reference.taker_inclusions[0]["key"]),
        expected_value=hexstr_to_bytes(reference.taker_inclusions[0]["value"]),
        full_node_api=offer_setup.full_node_api,
        data_layer=offer_setup.taker.data_layer,
        store_id=offer_setup.taker.id,
    )

    maker_history_result = await offer_setup.maker.api.get_root_history(request={"id": offer_setup.maker.id.hex()})
    maker_history = maker_history_result["root_history"]
    taker_history_result = await offer_setup.taker.api.get_root_history(request={"id": offer_setup.taker.id.hex()})
    taker_history = taker_history_result["root_history"]

    assert [generation["confirmed"] for generation in maker_history] == [True] * len(maker_history)
    assert [generation["root_hash"] for generation in maker_history] == [
        bytes32([0] * 32),
        *reference.maker_root_history,
    ]

    assert [generation["confirmed"] for generation in taker_history] == [True] * len(taker_history)
    assert [generation["root_hash"] for generation in taker_history] == [
        bytes32([0] * 32),
        *reference.taker_root_history,
    ]

    # TODO: test maker and taker fees


@pytest.mark.parametrize(
    argnames="reference",
    argvalues=[
        pytest.param(make_one_take_one_reference, id="one for one"),
        pytest.param(make_one_take_one_same_values_reference, id="one for one same values"),
        pytest.param(make_two_take_one_reference, id="two for one"),
        pytest.param(make_one_take_two_reference, id="one for two"),
        pytest.param(make_one_existing_take_one_reference, id="one existing for one"),
        pytest.param(make_one_take_one_existing_reference, id="one for one existing"),
        pytest.param(make_one_upsert_take_one_reference, id="one upsert for one"),
        pytest.param(make_one_take_one_upsert_reference, id="one for one upsert"),
    ],
)
@pytest.mark.parametrize(argnames="maker_or_taker", argvalues=["maker", "taker"])
@pytest.mark.anyio
async def test_make_and_then_take_offer_invalid_inclusion_key(
    reference: MakeAndTakeReference,
    maker_or_taker: str,
) -> None:
    broken_taker_offer = copy.deepcopy(reference.make_offer_response)
    if maker_or_taker == "maker":
        broken_taker_offer["maker"][0]["proofs"][0]["key"] += "ab"
    elif maker_or_taker == "taker":
        broken_taker_offer["taker"][0]["inclusions"][0]["key"] += "ab"
    else:  # pragma: no cover
        raise Exception("invalid maker or taker choice")

    offer_bytes = hexstr_to_bytes(broken_taker_offer["offer"])
    trading_offer = TradingOffer.from_bytes(offer_bytes)

    # TODO: specific exceptions
    with pytest.raises(OfferIntegrityError):
        verify_offer(
            maker=tuple(StoreProofs.unmarshal(proof) for proof in broken_taker_offer["maker"]),
            taker=tuple(OfferStore.unmarshal(offer_store) for offer_store in broken_taker_offer["taker"]),
            summary=await DataLayerWallet.get_offer_summary(offer=trading_offer),
        )


@pytest.mark.anyio
async def test_verify_offer_rpc_valid(bare_data_layer_api: DataLayerRpcApi) -> None:
    reference = make_one_take_one_reference

    verify_request = {
        "offer": reference.make_offer_response,
        "fee": 0,
    }
    verify_response = await bare_data_layer_api.verify_offer(request=verify_request)

    assert verify_response == {
        "success": True,
        "valid": True,
        "error": None,
        "fee": 0,
    }


@pytest.mark.anyio
async def test_verify_offer_rpc_invalid(bare_data_layer_api: DataLayerRpcApi) -> None:
    reference = make_one_take_one_reference
    broken_taker_offer = copy.deepcopy(reference.make_offer_response)
    broken_taker_offer["maker"][0]["proofs"][0]["key"] += "ab"

    verify_request = {
        "offer": broken_taker_offer,
        "fee": 0,
    }
    verify_response = await bare_data_layer_api.verify_offer(request=verify_request)

    assert verify_response == {
        "success": True,
        "valid": False,
        "error": "maker: node hash does not match key and value",
        "fee": None,
    }


@pytest.mark.anyio
async def test_make_offer_failure_rolls_back_db(offer_setup: OfferSetup) -> None:
    # TODO: only needs the maker and db?  wallet?
    reference = make_one_take_one_reference
    offer_setup = await populate_offer_setup(offer_setup=offer_setup, count=reference.entries_to_insert)

    maker_request = {
        "maker": [
            {
                "store_id": offer_setup.maker.id.hex(),
                "inclusions": reference.maker_inclusions,
            },
            {
                "store_id": bytes32([0] * 32).hex(),
                "inclusions": [],
            },
        ],
        "taker": [],
        "fee": 0,
    }

    with pytest.raises(Exception, match="store id not available"):
        await offer_setup.maker.api.make_offer(request=maker_request)

    pending_root = await offer_setup.maker.data_layer.data_store.get_pending_root(store_id=offer_setup.maker.id)
    assert pending_root is None


@pytest.mark.parametrize(
    argnames="reference",
    argvalues=[
        pytest.param(make_one_take_one_reference, id="one for one"),
        pytest.param(make_one_take_one_same_values_reference, id="one for one same values"),
        pytest.param(make_two_take_one_reference, id="two for one"),
        pytest.param(make_one_take_two_reference, id="one for two"),
        pytest.param(make_one_existing_take_one_reference, id="one existing for one"),
        pytest.param(make_one_take_one_existing_reference, id="one for one existing"),
        pytest.param(make_one_upsert_take_one_reference, id="one upsert for one"),
        pytest.param(make_one_take_one_upsert_reference, id="one for one upsert"),
        pytest.param(make_one_take_one_unpopulated_reference, id="one for one unpopulated"),
    ],
)
@pytest.mark.anyio
async def test_make_and_cancel_offer(offer_setup: OfferSetup, reference: MakeAndTakeReference) -> None:
    offer_setup = await populate_offer_setup(offer_setup=offer_setup, count=reference.entries_to_insert)

    maker_request = {
        "maker": [
            {
                "store_id": offer_setup.maker.id.hex(),
                "inclusions": reference.maker_inclusions,
            }
        ],
        "taker": [
            {
                "store_id": offer_setup.taker.id.hex(),
                "inclusions": reference.taker_inclusions,
            }
        ],
        "fee": 0,
    }
    maker_response = await offer_setup.maker.api.make_offer(request=maker_request)
    # print(f"\nmaybe_reference_offer = {maker_response['offer']}")

    # only check for success
    # due to differences in chain progression, the exact offer and trade id may differ from the reference
    # assert maker_response == {"success": True, "offer": reference.make_offer_response}
    assert maker_response["success"] is True

    cancel_request = {
        "trade_id": maker_response["offer"]["trade_id"],
        "secure": True,
        "fee": None,
    }
    await offer_setup.maker.api.cancel_offer(request=cancel_request)

    for _ in range(10):
        if not (
            await offer_setup.maker.data_layer.wallet_rpc.check_offer_validity(
                offer=TradingOffer.from_bytes(hexstr_to_bytes(maker_response["offer"]["offer"])),
            )
        )[1]:
            break
        await offer_setup.full_node_api.farm_blocks_to_puzzlehash(count=1, guarantee_transaction_blocks=True)
        await asyncio.sleep(0.5)
    else:  # pragma: no cover
        assert False, "offer was not cancelled"

    taker_request = {
        "offer": maker_response["offer"],
        "fee": 0,
    }

    with pytest.raises(ValueError, match="This offer is no longer valid"):
        await offer_setup.taker.api.take_offer(request=taker_request)


@pytest.mark.parametrize(
    argnames="reference",
    argvalues=[
        pytest.param(make_one_take_one_reference, id="one for one"),
        pytest.param(make_one_take_one_same_values_reference, id="one for one same values"),
        pytest.param(make_two_take_one_reference, id="two for one"),
        pytest.param(make_one_take_two_reference, id="one for two"),
        pytest.param(make_one_existing_take_one_reference, id="one existing for one"),
        pytest.param(make_one_take_one_existing_reference, id="one for one existing"),
        pytest.param(make_one_upsert_take_one_reference, id="one upsert for one"),
        pytest.param(make_one_take_one_upsert_reference, id="one for one upsert"),
        pytest.param(make_one_take_one_unpopulated_reference, id="one for one unpopulated"),
    ],
)
@pytest.mark.parametrize(
    argnames="secure",
    argvalues=[
        pytest.param(True, id="secure"),
        pytest.param(False, id="insecure"),
    ],
)
@pytest.mark.anyio
async def test_make_and_cancel_offer_then_update(
    offer_setup: OfferSetup, reference: MakeAndTakeReference, secure: bool
) -> None:
    offer_setup = await populate_offer_setup(offer_setup=offer_setup, count=reference.entries_to_insert)

    initial_local_root = await offer_setup.maker.data_layer.get_local_root(store_id=offer_setup.maker.id)

    maker_request = {
        "maker": [
            {
                "store_id": offer_setup.maker.id.hex(),
                "inclusions": reference.maker_inclusions,
            }
        ],
        "taker": [
            {
                "store_id": offer_setup.taker.id.hex(),
                "inclusions": reference.taker_inclusions,
            }
        ],
        "fee": 0,
    }
    maker_response = await offer_setup.maker.api.make_offer(request=maker_request)
    # print(f"\nmaybe_reference_offer = {maker_response['offer']}")

    # only check for success
    # due to differences in chain progression, the exact offer and trade id may differ from the reference
    # assert maker_response == {"success": True, "offer": reference.make_offer_response}
    assert maker_response["success"] is True

    cancel_request = {
        "trade_id": maker_response["offer"]["trade_id"],
        "secure": secure,
        "fee": None,
    }
    await offer_setup.maker.api.cancel_offer(request=cancel_request)

    if secure:
        offer_to_cancel = TradingOffer.from_bytes(hexstr_to_bytes(maker_response["offer"]["offer"]))

        await time_out_assert(
            timeout=20,
            function=process_block_and_check_offer_validity,
            value=False,
            offer=offer_to_cancel,
            offer_setup=offer_setup,
        )

    await time_out_assert(
        timeout=20,
        function=offer_setup.maker.data_layer.get_local_root,
        value=initial_local_root,
        store_id=offer_setup.maker.id,
    )

    await asyncio.sleep(10)

    post_key = b"\x37"
    post_value = b"\x38"

    await offer_setup.maker.api.batch_update(
        {
            "id": offer_setup.maker.id.hex(),
            "changelist": [{"action": "insert", "key": post_key.hex(), "value": post_value.hex()}],
        }
    )

    await process_for_data_layer_keys(
        expected_key=post_key,
        expected_value=post_value,
        full_node_api=offer_setup.full_node_api,
        data_layer=offer_setup.maker.data_layer,
        store_id=offer_setup.maker.id,
    )


@pytest.mark.parametrize(
    argnames="reference",
    argvalues=[
        pytest.param(make_one_take_one_reference, id="one for one"),
        pytest.param(make_two_take_one_reference, id="two for one"),
        pytest.param(make_one_take_two_reference, id="one for two"),
        pytest.param(make_one_take_one_existing_reference, id="one for one existing"),
        pytest.param(make_one_upsert_take_one_reference, id="one upsert for one"),
        pytest.param(make_one_take_one_upsert_reference, id="one for one upsert"),
        pytest.param(make_one_take_one_unpopulated_reference, id="one for one unpopulated"),
    ],
)
@pytest.mark.anyio
async def test_make_and_cancel_offer_not_secure_clears_pending_roots(
    offer_setup: OfferSetup,
    reference: MakeAndTakeReference,
) -> None:
    offer_setup = await populate_offer_setup(offer_setup=offer_setup, count=reference.entries_to_insert)

    maker_request = {
        "maker": [
            {
                "store_id": offer_setup.maker.id.hex(),
                "inclusions": reference.maker_inclusions,
            }
        ],
        "taker": [
            {
                "store_id": offer_setup.taker.id.hex(),
                "inclusions": reference.taker_inclusions,
            }
        ],
        "fee": 0,
    }
    maker_response = await offer_setup.maker.api.make_offer(request=maker_request)
    print(f"\nmaybe_reference_offer = {maker_response['offer']}")

    # only check for success
    # due to differences in chain progression, the exact offer and trade id may differ from the reference
    # assert maker_response == {"success": True, "offer": reference.make_offer_response}
    assert maker_response["success"] is True

    cancel_request = {
        "trade_id": maker_response["offer"]["trade_id"],
        "secure": False,
        "fee": None,
    }
    await offer_setup.maker.api.cancel_offer(request=cancel_request)

    # make sure there is no left over pending root by inserting and publishing
    await offer_setup.maker.api.insert(request={"id": offer_setup.maker.id.hex(), "key": "ab", "value": "cd"})


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_get_sync_status(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)

        key = b"a"
        value = b"\x00\x01"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)

        key_2 = b"b"
        value_2 = b"\x00\x01"
        changelist = [{"action": "insert", "key": key_2.hex(), "value": value_2.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)

        res_before = await data_rpc_api.get_root({"id": store_id.hex()})

        key_3 = b"c"
        value_3 = b"\x00\x01"
        changelist = [{"action": "insert", "key": key_3.hex(), "value": value_3.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec2 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec2, wallet_rpc_api)

        res_after = await data_rpc_api.get_root({"id": store_id.hex()})

        sync_status_res = await data_rpc_api.get_sync_status({"id": store_id.hex()})
        sync_status = sync_status_res["sync_status"]
        assert sync_status["root_hash"] == sync_status["target_root_hash"] == res_after["hash"].hex()
        assert sync_status["generation"] == sync_status["target_generation"] == 3

        await data_layer.data_store.rollback_to_generation(store_id, 2)
        sync_status_res = await data_rpc_api.get_sync_status({"id": store_id.hex()})
        sync_status = sync_status_res["sync_status"]

        assert sync_status["root_hash"] == res_before["hash"].hex()
        assert sync_status["target_root_hash"] == res_after["hash"].hex()
        assert sync_status["target_root_hash"] != sync_status["root_hash"]
        assert sync_status["generation"] == 2
        assert sync_status["target_generation"] == 3


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(argnames="layer", argvalues=list(InterfaceLayer))
@pytest.mark.anyio
async def test_clear_pending_roots(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    layer: InterfaceLayer,
    bt: BlockTools,
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer_service(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer_service:
        # NOTE: we don't need the service for direct...  simpler to leave it in
        assert data_layer_service.rpc_server is not None
        rpc_port = data_layer_service.rpc_server.listen_port
        data_layer = data_layer_service._api.data_layer
        # test insert
        data_rpc_api = DataLayerRpcApi(data_layer)

        data_store = data_layer.data_store

        store_id = bytes32(range(32))
        await data_store.create_tree(store_id=store_id, status=Status.COMMITTED)

        key = b"\x01\x02"
        value = b"abc"

        await data_store.insert(
            key=key,
            value=value,
            store_id=store_id,
            reference_node_hash=None,
            side=None,
            status=Status.PENDING,
        )

        pending_root = await data_store.get_pending_root(store_id=store_id)
        assert pending_root is not None

        if layer == InterfaceLayer.direct:
            cleared_root = await data_rpc_api.clear_pending_roots({"store_id": store_id.hex()})
        elif layer == InterfaceLayer.funcs:
            cleared_root = await clear_pending_roots(
                store_id=store_id,
                rpc_port=rpc_port,
                root_path=bt.root_path,
            )
        elif layer == InterfaceLayer.cli:
            args: List[str] = [
                sys.executable,
                "-m",
                "chia",
                "data",
                "clear_pending_roots",
                "--id",
                store_id.hex(),
                "--data-rpc-port",
                str(rpc_port),
                "--yes",
            ]
            process = await asyncio.create_subprocess_exec(
                *args,
                env={**os.environ, "CHIA_ROOT": str(bt.root_path)},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.wait()
            assert process.stdout is not None
            assert process.stderr is not None
            stdout = await process.stdout.read()
            cleared_root = json.loads(stdout)
            stderr = await process.stderr.read()
            assert process.returncode == 0
            if sys.version_info >= (3, 10, 6):
                assert stderr == b""
            else:  # pragma: no cover
                # https://github.com/python/cpython/issues/92841
                assert stderr == b"" or b"_ProactorBasePipeTransport.__del__" in stderr
        elif layer == InterfaceLayer.client:
            client = await DataLayerRpcClient.create(
                self_hostname=self_hostname,
                port=rpc_port,
                root_path=bt.root_path,
                net_config=bt.config,
            )
            try:
                cleared_root = await client.clear_pending_roots(store_id=store_id)
            finally:
                client.close()
                await client.await_closed()
        else:  # pragma: no cover
            assert False, "unhandled parametrization"

        assert cleared_root == {"success": True, "root": pending_root.marshal()}


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_issue_15955_deadlock(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )

    wallet_node = wallet_rpc_api.service
    wallet = wallet_node.wallet_state_manager.main_wallet

    interval = 1
    config = bt.config
    config["data_layer"]["manage_data_interval"] = interval
    bt.change_config(new_config=config)

    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        # get some xch
        await full_node_api.farm_blocks_to_wallet(count=1, wallet=wallet)
        await full_node_api.wait_for_wallet_synced(wallet_node)

        # create a store
        transaction_records, store_id = await data_layer.create_store(fee=uint64(0))
        await full_node_api.process_transaction_records(records=transaction_records)
        await full_node_api.wait_for_wallet_synced(wallet_node)
        assert await check_singleton_confirmed(dl=data_layer, store_id=store_id)

        # insert a key and value
        key = b"\x00"
        value = b"\x01" * 10_000
        transaction_record = await data_layer.batch_update(
            store_id=store_id,
            changelist=[{"action": "insert", "key": key, "value": value}],
            fee=uint64(0),
        )
        assert transaction_record is not None
        await full_node_api.process_transaction_records(records=[transaction_record])
        await full_node_api.wait_for_wallet_synced(wallet_node)
        assert await check_singleton_confirmed(dl=data_layer, store_id=store_id)

        # get the value a bunch through several periodic data management cycles
        concurrent_requests = 10
        time_per_request = 2
        timeout = concurrent_requests * time_per_request

        duration = 10 * interval
        start = time.monotonic()
        end = start + duration

        while time.monotonic() < end:
            with anyio.fail_after(adjusted_timeout(timeout)):
                await asyncio.gather(
                    *(asyncio.create_task(data_layer.get_value(store_id=store_id, key=key)) for _ in range(10))
                )


@pytest.mark.parametrize(argnames="maximum_full_file_count", argvalues=[1, 5, 100])
@boolean_datacases(name="group_files_by_store", false="group by singleton", true="don't group by singleton")
@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_maximum_full_file_count(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    maximum_full_file_count: int,
    group_files_by_store: bool,
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    manage_data_interval = 5
    async with init_data_layer(
        wallet_rpc_port=wallet_rpc_port,
        bt=bt,
        db_path=tmp_path,
        manage_data_interval=manage_data_interval,
        maximum_full_file_count=maximum_full_file_count,
        group_files_by_store=group_files_by_store,
    ) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        root_hashes: List[bytes32] = []
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_rpc_api.service, timeout=20)
        for batch_count in range(1, 10):
            key = batch_count.to_bytes(2, "big")
            value = batch_count.to_bytes(2, "big")
            changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
            res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
            update_tx_rec = res["tx_id"]
            await farm_block_with_spend(full_node_api, ph, update_tx_rec, wallet_rpc_api)
            await asyncio.sleep(manage_data_interval * 2)
            root_hash = await data_rpc_api.get_root({"id": store_id.hex()})
            root_hashes.append(root_hash["hash"])
            expected_files_count = min(batch_count, maximum_full_file_count) + batch_count
            server_files_location = (
                data_layer.server_files_location.joinpath(f"{store_id}")
                if group_files_by_store
                else data_layer.server_files_location
            )
            with os.scandir(server_files_location) as entries:
                filenames = {entry.name for entry in entries}
                assert len(filenames) == expected_files_count
            for generation, hash in enumerate(root_hashes):
                delta_path = get_delta_filename_path(
                    data_layer.server_files_location,
                    store_id,
                    hash,
                    generation + 1,
                    group_files_by_store,
                )
                assert delta_path.exists()
                full_file_path = get_full_tree_filename_path(
                    data_layer.server_files_location,
                    store_id,
                    hash,
                    generation + 1,
                    group_files_by_store,
                )
                if generation + 1 > batch_count - maximum_full_file_count:
                    assert full_file_path.exists()
                else:
                    assert not full_file_path.exists()


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_unsubscribe_unknown(
    bare_data_layer_api: DataLayerRpcApi,
    seeded_random: random.Random,
) -> None:
    with pytest.raises(RuntimeError, match="No subscription found for the given store_id."):
        await bare_data_layer_api.unsubscribe(request={"id": bytes32.random(seeded_random).hex(), "retain": False})


@pytest.mark.parametrize("retain", [True, False])
@boolean_datacases(name="group_files_by_store", false="group by singleton", true="don't group by singleton")
@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_unsubscribe_removes_files(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    retain: bool,
    group_files_by_store: bool,
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    manage_data_interval = 5
    async with init_data_layer(
        wallet_rpc_port=wallet_rpc_port,
        bt=bt,
        db_path=tmp_path,
        manage_data_interval=manage_data_interval,
        maximum_full_file_count=100,
        group_files_by_store=group_files_by_store,
    ) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        root_hashes: List[bytes32] = []
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)

        # subscribe to ourselves
        await data_rpc_api.subscribe(request={"id": store_id.hex()})
        update_count = 10
        for batch_count in range(update_count):
            key = batch_count.to_bytes(2, "big")
            value = batch_count.to_bytes(2, "big")
            changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
            res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
            update_tx_rec = res["tx_id"]
            await farm_block_with_spend(full_node_api, ph, update_tx_rec, wallet_rpc_api)
            await asyncio.sleep(manage_data_interval * 2)
            root_hash = await data_rpc_api.get_root({"id": store_id.hex()})
            root_hashes.append(root_hash["hash"])

        store_path = (
            data_layer.server_files_location.joinpath(f"{store_id}")
            if group_files_by_store
            else data_layer.server_files_location
        )
        filenames = {path.name for path in store_path.iterdir()}
        assert len(filenames) == 2 * update_count
        for generation, hash in enumerate(root_hashes):
            path = get_delta_filename_path(
                data_layer.server_files_location,
                store_id,
                hash,
                generation + 1,
                group_files_by_store,
            )
            assert path.exists()
            path = get_full_tree_filename_path(
                data_layer.server_files_location,
                store_id,
                hash,
                generation + 1,
                group_files_by_store,
            )
            assert path.exists()

        res = await data_rpc_api.unsubscribe(request={"id": store_id.hex(), "retain": retain})

        # wait for unsubscribe to be processed
        await asyncio.sleep(manage_data_interval * 3)

        filenames = {path.name for path in store_path.iterdir()}
        assert len(filenames) == (2 * update_count if retain else 0)


@pytest.mark.parametrize(argnames="layer", argvalues=list(InterfaceLayer))
@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_wallet_log_in_changes_active_fingerprint(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    layer: InterfaceLayer,
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    primary_fingerprint = cast(int, (await wallet_rpc_api.get_logged_in_fingerprint(request={}))["fingerprint"])

    mnemonic = create_mnemonic()
    assert wallet_rpc_api.service.local_keychain is not None
    private_key = wallet_rpc_api.service.local_keychain.add_key(mnemonic_or_pk=mnemonic)
    secondary_fingerprint: int = private_key.get_g1().get_fingerprint()

    await wallet_rpc_api.log_in(request={"fingerprint": primary_fingerprint})

    active_fingerprint = cast(int, (await wallet_rpc_api.get_logged_in_fingerprint(request={}))["fingerprint"])
    assert active_fingerprint == primary_fingerprint

    async with init_data_layer_service(wallet_rpc_port=wallet_rpc_port, bt=bt) as data_layer_service:
        # NOTE: we don't need the service for direct...  simpler to leave it in
        assert data_layer_service.rpc_server is not None
        rpc_port = data_layer_service.rpc_server.listen_port
        data_layer = data_layer_service._api.data_layer
        # test wallet log in
        data_rpc_api = DataLayerRpcApi(data_layer)

        if layer == InterfaceLayer.direct:
            await data_rpc_api.wallet_log_in({"fingerprint": secondary_fingerprint})
        elif layer == InterfaceLayer.client:
            client = await DataLayerRpcClient.create(
                self_hostname=self_hostname,
                port=rpc_port,
                root_path=bt.root_path,
                net_config=bt.config,
            )
            try:
                await client.wallet_log_in(fingerprint=secondary_fingerprint)
            finally:
                client.close()
                await client.await_closed()
        elif layer == InterfaceLayer.funcs:
            await wallet_log_in_cmd(rpc_port=rpc_port, fingerprint=secondary_fingerprint, root_path=bt.root_path)
        elif layer == InterfaceLayer.cli:
            process = await run_cli_cmd(
                "data",
                "wallet_log_in",
                "--fingerprint",
                str(secondary_fingerprint),
                "--data-rpc-port",
                str(rpc_port),
                root_path=bt.root_path,
            )
            assert process.stdout is not None
            assert await process.stdout.read() == b""
        else:  # pragma: no cover
            assert False, "unhandled parametrization"

        active_fingerprint = cast(int, (await wallet_rpc_api.get_logged_in_fingerprint(request={}))["fingerprint"])
        assert active_fingerprint == secondary_fingerprint


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_mirrors(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)

        urls = ["http://127.0.0.1/8000", "http://127.0.0.1/8001"]
        res = await data_rpc_api.add_mirror({"id": store_id.hex(), "urls": urls, "amount": 1, "fee": 1})

        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)
        mirrors = await data_rpc_api.get_mirrors({"id": store_id.hex()})
        mirror_list = mirrors["mirrors"]
        assert len(mirror_list) == 1
        mirror = mirror_list[0]
        assert mirror["urls"] == ["http://127.0.0.1/8000", "http://127.0.0.1/8001"]
        coin_id = mirror["coin_id"]

        res = await data_rpc_api.delete_mirror({"coin_id": coin_id, "fee": 1})
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)
        mirrors = await data_rpc_api.get_mirrors({"id": store_id.hex()})
        mirror_list = mirrors["mirrors"]
        assert len(mirror_list) == 0

        with pytest.raises(RuntimeError, match="URL list can't be empty"):
            res = await data_rpc_api.add_mirror({"id": store_id.hex(), "urls": [], "amount": 1, "fee": 1})


@dataclass(frozen=True)
class ProofReference:
    entries_to_insert: int
    keys_to_prove: List[str]
    verify_proof_response: Dict[str, Any]


def populate_reference(count: int, keys_to_prove: int) -> ProofReference:
    ret = ProofReference(
        entries_to_insert=count,
        keys_to_prove=[value.to_bytes(length=1, byteorder="big").hex() for value in range(keys_to_prove)],
        verify_proof_response={
            "current_root": True,
            "success": True,
            "verified_clvm_hashes": {
                "store_id": "",
                "inclusions": [
                    {
                        "key_clvm_hash": "0x" + std_hash(b"\1" + value.to_bytes(length=1, byteorder="big")).hex(),
                        "value_clvm_hash": "0x"
                        + std_hash(b"\1" + b"\x01" + value.to_bytes(length=1, byteorder="big")).hex(),
                    }
                    for value in range(keys_to_prove)
                ],
            },
        },
    )
    return ret


async def populate_proof_setup(offer_setup: OfferSetup, count: int) -> OfferSetup:
    if count > 0:
        # Only need data in the maker for proofs
        value_prefix = b"\x01"
        store_setup = offer_setup.maker
        await store_setup.api.batch_update(
            {
                "id": store_setup.id.hex(),
                "changelist": [
                    {
                        "action": "insert",
                        "key": value.to_bytes(length=1, byteorder="big").hex(),
                        "value": (value_prefix + value.to_bytes(length=1, byteorder="big")).hex(),
                    }
                    for value in range(count)
                ],
            }
        )

        await process_for_data_layer_keys(
            expected_key=b"\x00",
            full_node_api=offer_setup.full_node_api,
            data_layer=offer_setup.maker.data_layer,
            store_id=offer_setup.maker.id,
        )

    maker_original_singleton = await offer_setup.maker.data_layer.get_root(store_id=offer_setup.maker.id)
    assert maker_original_singleton is not None
    maker_original_root_hash = maker_original_singleton.root

    return OfferSetup(
        maker=StoreSetup(
            api=offer_setup.maker.api,
            id=offer_setup.maker.id,
            original_hash=maker_original_root_hash,
            data_layer=offer_setup.maker.data_layer,
            data_rpc_client=offer_setup.maker.data_rpc_client,
        ),
        taker=StoreSetup(
            api=offer_setup.taker.api,
            id=offer_setup.taker.id,
            original_hash=bytes32([0] * 32),
            data_layer=offer_setup.taker.data_layer,
            data_rpc_client=offer_setup.taker.data_rpc_client,
        ),
        full_node_api=offer_setup.full_node_api,
    )


@pytest.mark.parametrize(
    argnames="reference",
    argvalues=[
        pytest.param(populate_reference(count=5, keys_to_prove=1), id="one key"),
        pytest.param(populate_reference(count=5, keys_to_prove=2), id="two keys"),
        pytest.param(populate_reference(count=5, keys_to_prove=5), id="five keys"),
    ],
)
@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_dl_proof(offer_setup: OfferSetup, reference: ProofReference) -> None:
    offer_setup = await populate_proof_setup(offer_setup=offer_setup, count=reference.entries_to_insert)
    reference.verify_proof_response["verified_clvm_hashes"]["store_id"] = f"0x{offer_setup.maker.id.hex()}"

    #
    # Ideally this would use the InterfaceLayer as a parameterized list, however, all the fixtures
    # are function scoped, which makes it very long to run this but this doesn't change any of the
    # data, so rerunning all the setup for each test is not needed - module scope would be perfect
    # but it requires all the supporting fixtures (wallet/nodes/etc) to have the same scope
    #

    # random tests for HashOnlyProof root()
    fakeproof = HashOnlyProof(
        key_clvm_hash=bytes32([1] * 32), value_clvm_hash=bytes32([1] * 32), node_hash=bytes32([3] * 32), layers=[]
    )
    assert fakeproof.root() == fakeproof.node_hash

    fakeproof = HashOnlyProof(
        key_clvm_hash=bytes32([1] * 32),
        value_clvm_hash=bytes32([1] * 32),
        node_hash=bytes32([3] * 32),
        layers=[
            ProofLayer(other_hash_side=uint8(0), other_hash=bytes32([1] * 32), combined_hash=bytes32([5] * 32)),
            ProofLayer(other_hash_side=uint8(0), other_hash=bytes32([1] * 32), combined_hash=bytes32([7] * 32)),
        ],
    )
    assert fakeproof.root() == bytes32([7] * 32)

    # Test InterfaceLayer.direct
    proof = await offer_setup.maker.api.get_proof(
        request={"store_id": offer_setup.maker.id.hex(), "keys": reference.keys_to_prove}
    )
    assert proof["success"] is True
    verify = await offer_setup.taker.api.verify_proof(request=proof["proof"])
    assert verify == reference.verify_proof_response

    # test InterfaceLayer.client
    proof = dict()
    verify = dict()
    proof = await offer_setup.maker.data_rpc_client.get_proof(
        store_id=offer_setup.maker.id, keys=[hexstr_to_bytes(key) for key in reference.keys_to_prove]
    )
    assert proof["success"] is True
    verify = await offer_setup.taker.data_rpc_client.verify_proof(proof=proof["proof"])
    assert verify == reference.verify_proof_response

    # test InterfaceLayer.func
    proof = dict()
    verify = dict()
    proof = await get_proof_cmd(
        store_id=offer_setup.maker.id,
        key_strings=reference.keys_to_prove,
        rpc_port=offer_setup.maker.data_rpc_client.port,
        root_path=offer_setup.maker.data_layer.root_path,
    )
    assert proof["success"] is True
    verify = await verify_proof_cmd(
        proof=proof["proof"],
        rpc_port=offer_setup.taker.data_rpc_client.port,
        root_path=offer_setup.taker.data_layer.root_path,
    )
    assert verify == reference.verify_proof_response

    # test InterfaceLayer.cli
    key_args: List[str] = []
    for key in reference.keys_to_prove:
        key_args.append("--key")
        key_args.append(key)

    process = await run_cli_cmd(
        "data",
        "get_proof",
        "--id",
        offer_setup.maker.id.hex(),
        *key_args,
        "--data-rpc-port",
        str(offer_setup.maker.data_rpc_client.port),
        root_path=offer_setup.maker.data_layer.root_path,
    )
    assert process.stdout is not None
    raw_output = await process.stdout.read()
    proof = json.loads(raw_output)
    assert proof["success"] is True

    process = await run_cli_cmd(
        "data",
        "verify_proof",
        "-p",
        json.dumps(proof["proof"]),
        "--data-rpc-port",
        str(offer_setup.taker.data_rpc_client.port),
        root_path=offer_setup.taker.data_layer.root_path,
    )
    assert process.stdout is not None
    raw_output = await process.stdout.read()
    verify = json.loads(raw_output)
    assert verify == reference.verify_proof_response


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_dl_proof_errors(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        fakeroot = bytes32([4] * 32)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)

        with pytest.raises(ValueError, match="no root"):
            await data_rpc_api.get_proof(request={"store_id": fakeroot.hex(), "keys": []})

        with pytest.raises(Exception, match="No generations found"):
            await data_rpc_api.get_proof(request={"store_id": store_id.hex(), "keys": [b"4".hex()]})

        changelist: List[Dict[str, str]] = [{"action": "insert", "key": b"a".hex(), "value": b"\x00\x01".hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)

        with pytest.raises(KeyNotFoundError, match="Key not found"):
            await data_rpc_api.get_proof(request={"store_id": store_id.hex(), "keys": [b"4".hex()]})


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_dl_proof_verify_errors(offer_setup: OfferSetup, seeded_random: random.Random) -> None:
    two_key_proof = populate_reference(count=5, keys_to_prove=2)
    offer_setup = await populate_proof_setup(offer_setup=offer_setup, count=two_key_proof.entries_to_insert)
    two_key_proof.verify_proof_response["verified_clvm_hashes"]["store_id"] = f"0x{offer_setup.maker.id.hex()}"

    proof = await offer_setup.maker.api.get_proof(
        request={"store_id": offer_setup.maker.id.hex(), "keys": two_key_proof.keys_to_prove}
    )
    assert proof["success"] is True

    verify = await offer_setup.taker.api.verify_proof(request=proof["proof"])
    assert verify == two_key_proof.verify_proof_response

    # test bad coin id
    badproof = deepcopy(proof["proof"])
    badproof["coin_id"] = bytes32.random(seeded_random).hex()
    with pytest.raises(ValueError, match="Invalid Proof: No DL singleton found at coin id"):
        await offer_setup.taker.api.verify_proof(request=badproof)

    # test bad innerpuz
    badproof = deepcopy(proof["proof"])
    badproof["inner_puzzle_hash"] = bytes32.random(seeded_random).hex()
    with pytest.raises(ValueError, match="Invalid Proof: incorrect puzzle hash"):
        await offer_setup.taker.api.verify_proof(request=badproof)

    # test bad key
    badproof = deepcopy(proof["proof"])
    badproof["store_proofs"]["proofs"][0]["key_clvm_hash"] = bytes32.random(seeded_random).hex()
    with pytest.raises(ValueError, match="Invalid Proof: node hash does not match key and value"):
        await offer_setup.taker.api.verify_proof(request=badproof)

    # test bad value
    badproof = deepcopy(proof["proof"])
    badproof["store_proofs"]["proofs"][0]["value_clvm_hash"] = bytes32.random(seeded_random).hex()
    with pytest.raises(ValueError, match="Invalid Proof: node hash does not match key and value"):
        await offer_setup.taker.api.verify_proof(request=badproof)

    # test bad layer hash
    badproof = deepcopy(proof["proof"])
    badproof["store_proofs"]["proofs"][0]["layers"][1]["other_hash"] = bytes32.random(seeded_random).hex()
    with pytest.raises(ValueError, match="Invalid Proof: invalid proof of inclusion found"):
        await offer_setup.taker.api.verify_proof(request=badproof)


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_dl_proof_changed_root(offer_setup: OfferSetup, seeded_random: random.Random) -> None:
    two_key_proof = populate_reference(count=5, keys_to_prove=2)
    offer_setup = await populate_proof_setup(offer_setup=offer_setup, count=two_key_proof.entries_to_insert)
    two_key_proof.verify_proof_response["verified_clvm_hashes"]["store_id"] = f"0x{offer_setup.maker.id.hex()}"

    proof = await offer_setup.maker.api.get_proof(
        request={"store_id": offer_setup.maker.id.hex(), "keys": two_key_proof.keys_to_prove}
    )
    assert proof["success"] is True

    verify = await offer_setup.taker.api.verify_proof(request=proof["proof"])
    assert verify == two_key_proof.verify_proof_response

    key = b"a"
    value = b"\x00\x01"
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
    await offer_setup.maker.api.batch_update({"id": offer_setup.maker.id.hex(), "changelist": changelist})

    await process_for_data_layer_keys(
        expected_key=key,
        expected_value=value,
        full_node_api=offer_setup.full_node_api,
        data_layer=offer_setup.maker.data_layer,
        store_id=offer_setup.maker.id,
    )

    root_changed = await offer_setup.taker.api.verify_proof(request=proof["proof"])
    assert root_changed == {**verify, "current_root": False}


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_pagination_rpcs(
    self_hostname: str, one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices, tmp_path: Path
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    # TODO: with this being a pseudo context manager'ish thing it doesn't actually handle shutdown
    async with init_data_layer(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer:
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)
        key1 = b"aa"
        value1 = b"\x01\x02"
        key1_hash = key_hash(key1)
        leaf_hash1 = leaf_hash(key1, value1)
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key1.hex(), "value": value1.hex()}]
        key2 = b"ba"
        value2 = b"\x03\x02"
        key2_hash = key_hash(key2)
        leaf_hash2 = leaf_hash(key2, value2)
        changelist.append({"action": "insert", "key": key2.hex(), "value": value2.hex()})
        key3 = b"ccc"
        value3 = b"\x04\x05"
        changelist.append({"action": "insert", "key": key3.hex(), "value": value3.hex()})
        leaf_hash3 = leaf_hash(key3, value3)
        key4 = b"d"
        value4 = b"\x06\x03"
        key4_hash = key_hash(key4)
        leaf_hash4 = leaf_hash(key4, value4)
        changelist.append({"action": "insert", "key": key4.hex(), "value": value4.hex()})
        key5 = b"e"
        value5 = b"\x07\x01"
        key5_hash = key_hash(key5)
        leaf_hash5 = leaf_hash(key5, value5)
        changelist.append({"action": "insert", "key": key5.hex(), "value": value5.hex()})
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
        local_root = await data_rpc_api.get_local_root({"id": store_id.hex()})

        keys_reference = {
            "total_pages": 2,
            "total_bytes": 9,
            "keys": [],
            "root_hash": local_root["hash"],
        }

        keys_paginated = await data_rpc_api.get_keys({"id": store_id.hex(), "page": 0, "max_page_size": 5})
        assert key2_hash < key1_hash
        assert keys_paginated == {**keys_reference, "keys": ["0x" + key3.hex(), "0x" + key2.hex()]}

        keys_paginated = await data_rpc_api.get_keys({"id": store_id.hex(), "page": 1, "max_page_size": 5})
        assert key5_hash < key4_hash
        assert keys_paginated == {**keys_reference, "keys": ["0x" + key1.hex(), "0x" + key5.hex(), "0x" + key4.hex()]}

        keys_paginated = await data_rpc_api.get_keys({"id": store_id.hex(), "page": 2, "max_page_size": 5})
        assert keys_paginated == keys_reference

        keys_values_reference = {
            "total_pages": 3,
            "total_bytes": 19,
            "keys_values": [],
            "root_hash": local_root["hash"],
        }
        keys_values_paginated = await data_rpc_api.get_keys_values(
            {"id": store_id.hex(), "page": 0, "max_page_size": 8},
        )
        expected_kv = [
            {"atom": None, "hash": "0x" + leaf_hash3.hex(), "key": "0x" + key3.hex(), "value": "0x" + value3.hex()},
        ]
        assert keys_values_paginated == {**keys_values_reference, "keys_values": expected_kv}

        keys_values_paginated = await data_rpc_api.get_keys_values(
            {"id": store_id.hex(), "page": 1, "max_page_size": 8}
        )
        expected_kv = [
            {"atom": None, "hash": "0x" + leaf_hash1.hex(), "key": "0x" + key1.hex(), "value": "0x" + value1.hex()},
            {"atom": None, "hash": "0x" + leaf_hash2.hex(), "key": "0x" + key2.hex(), "value": "0x" + value2.hex()},
        ]
        assert leaf_hash1 < leaf_hash2
        assert keys_values_paginated == {**keys_values_reference, "keys_values": expected_kv}

        keys_values_paginated = await data_rpc_api.get_keys_values(
            {"id": store_id.hex(), "page": 2, "max_page_size": 8}
        )
        expected_kv = [
            {"atom": None, "hash": "0x" + leaf_hash5.hex(), "key": "0x" + key5.hex(), "value": "0x" + value5.hex()},
            {"atom": None, "hash": "0x" + leaf_hash4.hex(), "key": "0x" + key4.hex(), "value": "0x" + value4.hex()},
        ]
        assert leaf_hash5 < leaf_hash4
        assert keys_values_paginated == {**keys_values_reference, "keys_values": expected_kv}

        keys_values_paginated = await data_rpc_api.get_keys_values(
            {"id": store_id.hex(), "page": 3, "max_page_size": 8}
        )
        assert keys_values_paginated == keys_values_reference

        key6 = b"ab"
        value6 = b"\x01\x01"
        leaf_hash6 = leaf_hash(key6, value6)
        key7 = b"ac"
        value7 = b"\x01\x01"
        leaf_hash7 = leaf_hash(key7, value7)

        changelist = [{"action": "delete", "key": key3.hex()}]
        changelist.append({"action": "insert", "key": key6.hex(), "value": value6.hex()})
        changelist.append({"action": "insert", "key": key7.hex(), "value": value7.hex()})

        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec1 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)

        history = await data_rpc_api.get_root_history({"id": store_id.hex()})
        hash1 = history["root_history"][1]["root_hash"]
        hash2 = history["root_history"][2]["root_hash"]
        diff_reference = {
            "total_pages": 3,
            "total_bytes": 13,
            "diff": [],
        }
        diff_res = await data_rpc_api.get_kv_diff(
            {
                "id": store_id.hex(),
                "hash_1": hash1.hex(),
                "hash_2": hash2.hex(),
                "page": 0,
                "max_page_size": 5,
            }
        )
        expected_diff = [{"type": "DELETE", "key": key3.hex(), "value": value3.hex()}]
        assert diff_res == {**diff_reference, "diff": expected_diff}

        diff_res = await data_rpc_api.get_kv_diff(
            {
                "id": store_id.hex(),
                "hash_1": hash1.hex(),
                "hash_2": hash2.hex(),
                "page": 1,
                "max_page_size": 5,
            }
        )
        assert leaf_hash6 < leaf_hash7
        expected_diff = [{"type": "INSERT", "key": key6.hex(), "value": value6.hex()}]
        assert diff_res == {**diff_reference, "diff": expected_diff}

        diff_res = await data_rpc_api.get_kv_diff(
            {
                "id": store_id.hex(),
                "hash_1": hash1.hex(),
                "hash_2": hash2.hex(),
                "page": 2,
                "max_page_size": 5,
            }
        )
        expected_diff = [{"type": "INSERT", "key": key7.hex(), "value": value7.hex()}]
        assert diff_res == {**diff_reference, "diff": expected_diff}

        diff_res = await data_rpc_api.get_kv_diff(
            {
                "id": store_id.hex(),
                "hash_1": hash1.hex(),
                "hash_2": hash2.hex(),
                "page": 3,
                "max_page_size": 5,
            }
        )
        assert diff_res == diff_reference

        invalid_hash = bytes32([0] * 31 + [1])
        with pytest.raises(Exception, match=f"Unable to diff: Can't find keys and values for {invalid_hash.hex()}"):
            await data_rpc_api.get_kv_diff(
                {
                    "id": store_id.hex(),
                    "hash_1": hash1.hex(),
                    "hash_2": invalid_hash.hex(),
                    "page": 0,
                    "max_page_size": 10,
                }
            )

        with pytest.raises(Exception, match=f"Unable to diff: Can't find keys and values for {invalid_hash.hex()}"):
            diff_res = await data_rpc_api.get_kv_diff(
                {
                    "id": store_id.hex(),
                    "hash_1": invalid_hash.hex(),
                    "hash_2": hash2.hex(),
                    "page": 0,
                    "max_page_size": 10,
                }
            )

        new_value = b"\x02\x02"
        changelist = [{"action": "upsert", "key": key6.hex(), "value": new_value.hex()}]
        new_leaf_hash = leaf_hash(key6, new_value)
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec3 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec3, wallet_rpc_api)

        history = await data_rpc_api.get_root_history({"id": store_id.hex()})
        hash1 = history["root_history"][2]["root_hash"]
        hash2 = history["root_history"][3]["root_hash"]

        diff_res = await data_rpc_api.get_kv_diff(
            {
                "id": store_id.hex(),
                "hash_1": hash1.hex(),
                "hash_2": hash2.hex(),
                "page": 0,
                "max_page_size": 100,
            }
        )
        assert leaf_hash6 < new_leaf_hash
        diff_reference = {
            "total_pages": 1,
            "total_bytes": 8,
            "diff": [
                {"type": "DELETE", "key": key6.hex(), "value": value6.hex()},
                {"type": "INSERT", "key": key6.hex(), "value": new_value.hex()},
            ],
        }
        assert diff_res == diff_reference

        with pytest.raises(Exception, match="Can't find keys"):
            await data_rpc_api.get_keys(
                {"id": store_id.hex(), "page": 0, "max_page_size": 100, "root_hash": bytes32([0] * 31 + [1]).hex()}
            )

        with pytest.raises(Exception, match="Can't find keys and values"):
            await data_rpc_api.get_keys_values(
                {"id": store_id.hex(), "page": 0, "max_page_size": 100, "root_hash": bytes32([0] * 31 + [1]).hex()}
            )

        with pytest.raises(RuntimeError, match="Cannot paginate data, item size is larger than max page size"):
            keys_paginated = await data_rpc_api.get_keys_values({"id": store_id.hex(), "page": 0, "max_page_size": 1})

        with pytest.raises(RuntimeError, match="Cannot paginate data, item size is larger than max page size"):
            keys_values_paginated = await data_rpc_api.get_keys_values(
                {"id": store_id.hex(), "page": 0, "max_page_size": 1}
            )

        with pytest.raises(RuntimeError, match="Cannot paginate data, item size is larger than max page size"):
            diff_res = await data_rpc_api.get_kv_diff(
                {
                    "id": store_id.hex(),
                    "hash_1": hash1.hex(),
                    "hash_2": hash2.hex(),
                    "page": 0,
                    "max_page_size": 1,
                }
            )


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(argnames="layer", argvalues=[InterfaceLayer.funcs, InterfaceLayer.cli, InterfaceLayer.client])
@pytest.mark.parametrize(argnames="max_page_size", argvalues=[5, 100, None])
@pytest.mark.anyio
async def test_pagination_cmds(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    layer: InterfaceLayer,
    max_page_size: Optional[int],
    bt: BlockTools,
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer_service(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer_service:
        assert data_layer_service.rpc_server is not None
        rpc_port = data_layer_service.rpc_server.listen_port
        data_layer = data_layer_service._api.data_layer
        data_rpc_api = DataLayerRpcApi(data_layer)

        res = await data_rpc_api.create_data_store({})
        assert res is not None
        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)

        key = b"aa"
        value = b"aa"
        key_2 = b"aaaa"
        value_2 = b"a"

        changelist = [
            {"action": "insert", "key": key.hex(), "value": value.hex()},
            {"action": "insert", "key": key_2.hex(), "value": value_2.hex()},
        ]

        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
        local_root = await data_rpc_api.get_local_root({"id": store_id.hex()})
        hash_1 = bytes32([0] * 32)
        hash_2 = local_root["hash"]
        # `InterfaceLayer.direct` is not tested here since test `test_pagination_rpcs` extensively use it.
        if layer == InterfaceLayer.funcs:
            keys = await get_keys_cmd(
                rpc_port=rpc_port,
                store_id=store_id,
                root_hash=None,
                fingerprint=None,
                page=0,
                max_page_size=max_page_size,
                root_path=bt.root_path,
            )
            keys_values = await get_keys_values_cmd(
                rpc_port=rpc_port,
                store_id=store_id,
                root_hash=None,
                fingerprint=None,
                page=0,
                max_page_size=max_page_size,
                root_path=bt.root_path,
            )
            kv_diff = await get_kv_diff_cmd(
                rpc_port=rpc_port,
                store_id=store_id,
                hash_1=hash_1,
                hash_2=hash_2,
                fingerprint=None,
                page=0,
                max_page_size=max_page_size,
                root_path=bt.root_path,
            )
        elif layer == InterfaceLayer.cli:
            for command in ("get_keys", "get_keys_values", "get_kv_diff"):
                if command == "get_keys" or command == "get_keys_values":
                    args: List[str] = [
                        sys.executable,
                        "-m",
                        "chia",
                        "data",
                        command,
                        "--id",
                        store_id.hex(),
                        "--data-rpc-port",
                        str(rpc_port),
                        "--page",
                        "0",
                    ]
                else:
                    args = [
                        sys.executable,
                        "-m",
                        "chia",
                        "data",
                        command,
                        "--id",
                        store_id.hex(),
                        "--hash_1",
                        "0x" + hash_1.hex(),
                        "--hash_2",
                        "0x" + hash_2.hex(),
                        "--data-rpc-port",
                        str(rpc_port),
                        "--page",
                        "0",
                    ]
                if max_page_size is not None:
                    args.append("--max-page-size")
                    args.append(f"{max_page_size}")
                process = await asyncio.create_subprocess_exec(
                    *args,
                    env={**os.environ, "CHIA_ROOT": str(bt.root_path)},
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await process.wait()
                assert process.stdout is not None
                assert process.stderr is not None
                stdout = await process.stdout.read()
                stderr = await process.stderr.read()
                if command == "get_keys":
                    keys = json.loads(stdout)
                elif command == "get_keys_values":
                    keys_values = json.loads(stdout)
                else:
                    kv_diff = json.loads(stdout)
                assert process.returncode == 0
                if sys.version_info >= (3, 10, 6):
                    assert stderr == b""
                else:  # pragma: no cover
                    # https://github.com/python/cpython/issues/92841
                    assert stderr == b"" or b"_ProactorBasePipeTransport.__del__" in stderr
        elif layer == InterfaceLayer.client:
            client = await DataLayerRpcClient.create(
                self_hostname=self_hostname,
                port=rpc_port,
                root_path=bt.root_path,
                net_config=bt.config,
            )
            try:
                keys = await client.get_keys(
                    store_id=store_id,
                    root_hash=None,
                    page=0,
                    max_page_size=max_page_size,
                )
                keys_values = await client.get_keys_values(
                    store_id=store_id,
                    root_hash=None,
                    page=0,
                    max_page_size=max_page_size,
                )
                kv_diff = await client.get_kv_diff(
                    store_id=store_id,
                    hash_1=hash_1,
                    hash_2=hash_2,
                    page=0,
                    max_page_size=max_page_size,
                )
            finally:
                client.close()
                await client.await_closed()
        else:  # pragma: no cover
            assert False, "unhandled parametrization"
        if max_page_size is None or max_page_size == 100:
            assert keys == {
                "keys": ["0x61616161", "0x6161"],
                "root_hash": "0x889a4a61b17be799ae9d36831246672ef857a24091f54481431a83309d4e890e",
                "success": True,
                "total_bytes": 6,
                "total_pages": 1,
            }
            assert keys_values == {
                "keys_values": [
                    {
                        "atom": None,
                        "hash": "0x3c8ecfd41a1c54820f5ad687a4cbfbad0faa78445cbf31ec4f879ce553216a9d",
                        "key": "0x61616161",
                        "value": "0x61",
                    },
                    {
                        "atom": None,
                        "hash": "0x5a7edd8e4bc28e32ba2a2514054f3872037a4f6da52c5a662969b6b881beaa3f",
                        "key": "0x6161",
                        "value": "0x6161",
                    },
                ],
                "root_hash": "0x889a4a61b17be799ae9d36831246672ef857a24091f54481431a83309d4e890e",
                "success": True,
                "total_bytes": 9,
                "total_pages": 1,
            }
            assert kv_diff == {
                "diff": [
                    {"key": "61616161", "type": "INSERT", "value": "61"},
                    {"key": "6161", "type": "INSERT", "value": "6161"},
                ],
                "success": True,
                "total_bytes": 9,
                "total_pages": 1,
            }
        elif max_page_size == 5:
            assert keys == {
                "keys": ["0x61616161"],
                "root_hash": "0x889a4a61b17be799ae9d36831246672ef857a24091f54481431a83309d4e890e",
                "success": True,
                "total_bytes": 6,
                "total_pages": 2,
            }
            assert keys_values == {
                "keys_values": [
                    {
                        "atom": None,
                        "hash": "0x3c8ecfd41a1c54820f5ad687a4cbfbad0faa78445cbf31ec4f879ce553216a9d",
                        "key": "0x61616161",
                        "value": "0x61",
                    }
                ],
                "root_hash": "0x889a4a61b17be799ae9d36831246672ef857a24091f54481431a83309d4e890e",
                "success": True,
                "total_bytes": 9,
                "total_pages": 2,
            }
            assert kv_diff == {
                "diff": [
                    {"key": "61616161", "type": "INSERT", "value": "61"},
                ],
                "success": True,
                "total_bytes": 9,
                "total_pages": 2,
            }
        else:  # pragma: no cover
            assert False, "unhandled parametrization"


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(argnames="layer", argvalues=list(InterfaceLayer))
@pytest.mark.anyio
async def test_unsubmitted_batch_update(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    layer: InterfaceLayer,
    bt: BlockTools,
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    # Number of farmed blocks to check our batch update was not submitted.
    NUM_BLOCKS_WITHOUT_SUBMIT = 10
    async with init_data_layer_service(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer_service:
        assert data_layer_service.rpc_server is not None
        rpc_port = data_layer_service.rpc_server.listen_port
        data_layer = data_layer_service._api.data_layer
        data_rpc_api = DataLayerRpcApi(data_layer)

        res = await data_rpc_api.create_data_store({})
        assert res is not None

        store_id = bytes32.from_hexstr(res["id"])
        await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)

        to_insert = [(b"a", b"\x00\x01"), (b"b", b"\x00\x02"), (b"c", b"\x00\x03")]
        for key, value in to_insert:
            changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]

            if layer == InterfaceLayer.direct:
                res = await data_rpc_api.batch_update(
                    {"id": store_id.hex(), "changelist": changelist, "submit_on_chain": False}
                )
                assert res == {}
            elif layer == InterfaceLayer.funcs:
                res = await update_data_store_cmd(
                    rpc_port=rpc_port,
                    store_id=store_id,
                    changelist=changelist,
                    fee=None,
                    fingerprint=None,
                    submit_on_chain=False,
                    root_path=bt.root_path,
                )
                assert res == {"success": True}
            elif layer == InterfaceLayer.cli:
                args: List[str] = [
                    sys.executable,
                    "-m",
                    "chia",
                    "data",
                    "update_data_store",
                    "--id",
                    store_id.hex(),
                    "--changelist",
                    json.dumps(changelist),
                    "--no-submit",
                    "--data-rpc-port",
                    str(rpc_port),
                ]
                process = await asyncio.create_subprocess_exec(
                    *args,
                    env={**os.environ, "CHIA_ROOT": str(bt.root_path)},
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await process.wait()
                assert process.stdout is not None
                assert process.stderr is not None
                stdout = await process.stdout.read()
                res = json.loads(stdout)
                stderr = await process.stderr.read()
                assert process.returncode == 0
                if sys.version_info >= (3, 10, 6):
                    assert stderr == b""
                else:  # pragma: no cover
                    # https://github.com/python/cpython/issues/92841
                    assert stderr == b"" or b"_ProactorBasePipeTransport.__del__" in stderr
                assert res == {"success": True}
            elif layer == InterfaceLayer.client:
                client = await DataLayerRpcClient.create(
                    self_hostname=self_hostname,
                    port=rpc_port,
                    root_path=bt.root_path,
                    net_config=bt.config,
                )
                try:
                    res = await client.update_data_store(
                        store_id=store_id,
                        changelist=changelist,
                        fee=None,
                        submit_on_chain=False,
                    )
                    assert res == {"success": True}
                finally:
                    client.close()
                    await client.await_closed()
            else:  # pragma: no cover
                assert False, "unhandled parametrization"

            await full_node_api.farm_blocks_to_puzzlehash(
                count=NUM_BLOCKS_WITHOUT_SUBMIT, guarantee_transaction_blocks=True
            )
            keys_values = await data_rpc_api.get_keys_values({"id": store_id.hex()})
            assert keys_values == {"keys_values": []}
            pending_root = await data_layer.data_store.get_pending_root(store_id=store_id)
            assert pending_root is not None
            assert pending_root.status == Status.PENDING_BATCH

        key = b"d"
        value = b"\x00\x04"
        to_insert.append((key, value))

        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
        update_tx_rec0 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)

        keys_values = await data_rpc_api.get_keys_values({"id": store_id.hex()})
        assert len(keys_values["keys_values"]) == len(to_insert)
        kv_dict = {item["key"]: item["value"] for item in keys_values["keys_values"]}
        for key, value in to_insert:
            assert kv_dict["0x" + key.hex()] == "0x" + value.hex()
        prev_keys_values = keys_values
        old_root = await data_layer.data_store.get_tree_root(store_id=store_id)

        key = b"e"
        value = b"\x00\x05"
        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        res = await data_rpc_api.batch_update(
            {"id": store_id.hex(), "changelist": changelist, "submit_on_chain": False}
        )
        assert res == {}

        await full_node_api.farm_blocks_to_puzzlehash(
            count=NUM_BLOCKS_WITHOUT_SUBMIT, guarantee_transaction_blocks=True
        )
        root = await data_layer.data_store.get_tree_root(store_id=store_id)
        assert root == old_root

        key = b"f"
        value = b"\x00\x06"
        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        res = await data_rpc_api.batch_update(
            {"id": store_id.hex(), "changelist": changelist, "submit_on_chain": False}
        )
        assert res == {}

        await full_node_api.farm_blocks_to_puzzlehash(
            count=NUM_BLOCKS_WITHOUT_SUBMIT, guarantee_transaction_blocks=True
        )

        await data_rpc_api.clear_pending_roots({"store_id": store_id.hex()})
        pending_root = await data_layer.data_store.get_pending_root(store_id=store_id)
        assert pending_root is None
        root = await data_layer.data_store.get_tree_root(store_id=store_id)
        assert root == old_root

        key = b"g"
        value = b"\x00\x07"
        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        to_insert.append((key, value))

        res = await data_rpc_api.batch_update(
            {"id": store_id.hex(), "changelist": changelist, "submit_on_chain": False}
        )
        assert res == {}

        await full_node_api.farm_blocks_to_puzzlehash(
            count=NUM_BLOCKS_WITHOUT_SUBMIT, guarantee_transaction_blocks=True
        )
        keys_values = await data_rpc_api.get_keys_values({"id": store_id.hex()})
        assert keys_values == prev_keys_values

        pending_root = await data_layer.data_store.get_pending_root(store_id=store_id)
        assert pending_root is not None
        assert pending_root.status == Status.PENDING_BATCH

        # submit pending root
        if layer == InterfaceLayer.direct:
            res = await data_rpc_api.submit_pending_root({"id": store_id.hex()})
            update_tx_rec1 = res["tx_id"]
        elif layer == InterfaceLayer.funcs:
            res = await submit_pending_root_cmd(
                store_id=store_id,
                fee=None,
                fingerprint=None,
                rpc_port=rpc_port,
                root_path=bt.root_path,
            )
            update_tx_rec1 = bytes32.from_hexstr(res["tx_id"])
        elif layer == InterfaceLayer.cli:
            args = [
                sys.executable,
                "-m",
                "chia",
                "data",
                "submit_pending_root",
                "--id",
                store_id.hex(),
                "--data-rpc-port",
                str(rpc_port),
            ]
            process = await asyncio.create_subprocess_exec(
                *args,
                env={**os.environ, "CHIA_ROOT": str(bt.root_path)},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await process.wait()
            assert process.stdout is not None
            assert process.stderr is not None
            stdout = await process.stdout.read()
            res = json.loads(stdout)
            stderr = await process.stderr.read()
            assert process.returncode == 0
            if sys.version_info >= (3, 10, 6):
                assert stderr == b""
            else:  # pragma: no cover
                # https://github.com/python/cpython/issues/92841
                assert stderr == b"" or b"_ProactorBasePipeTransport.__del__" in stderr
            update_tx_rec1 = bytes32.from_hexstr(res["tx_id"])
        elif layer == InterfaceLayer.client:
            client = await DataLayerRpcClient.create(
                self_hostname=self_hostname,
                port=rpc_port,
                root_path=bt.root_path,
                net_config=bt.config,
            )
            try:
                res = await client.submit_pending_root(store_id=store_id, fee=None)
                update_tx_rec1 = bytes32.from_hexstr(res["tx_id"])
            finally:
                client.close()
                await client.await_closed()
        else:  # pragma: no cover
            assert False, "unhandled parametrization"

        pending_root = await data_layer.data_store.get_pending_root(store_id=store_id)
        assert pending_root is not None
        assert pending_root.status == Status.PENDING

        key = b"h"
        value = b"\x00\x08"
        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        with pytest.raises(Exception, match="Already have a pending root waiting for confirmation"):
            res = await data_rpc_api.batch_update(
                {"id": store_id.hex(), "changelist": changelist, "submit_on_chain": False}
            )
        with pytest.raises(Exception, match="Pending root is already submitted"):
            res = await data_rpc_api.submit_pending_root({"id": store_id.hex()})

        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)

        keys_values = await data_rpc_api.get_keys_values({"id": store_id.hex()})
        assert len(keys_values["keys_values"]) == len(to_insert)
        kv_dict = {item["key"]: item["value"] for item in keys_values["keys_values"]}
        for key, value in to_insert:
            assert kv_dict["0x" + key.hex()] == "0x" + value.hex()

        with pytest.raises(Exception, match="Latest root is already confirmed"):
            res = await data_rpc_api.submit_pending_root({"id": store_id.hex()})


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.parametrize(argnames="layer", argvalues=list(InterfaceLayer))
@boolean_datacases(name="submit_on_chain", false="save as incomplete batch", true="submit directly on chain")
@pytest.mark.anyio
async def test_multistore_update(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    layer: InterfaceLayer,
    submit_on_chain: bool,
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    async with init_data_layer_service(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer_service:
        assert data_layer_service.rpc_server is not None
        rpc_port = data_layer_service.rpc_server.listen_port

        data_layer = data_layer_service._api.data_layer
        data_store = data_layer.data_store
        data_rpc_api = DataLayerRpcApi(data_layer)

        store_ids: List[bytes32] = []
        store_ids_count = 5

        for _ in range(store_ids_count):
            res = await data_rpc_api.create_data_store({})
            assert res is not None
            store_id = bytes32.from_hexstr(res["id"])
            await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)
            store_ids.append(store_id)

        store_updates: List[Dict[str, Any]] = []
        key_offset = 1000
        for index, store_id in enumerate(store_ids):
            changelist: List[Dict[str, str]] = []
            key = index.to_bytes(2, "big")
            value = index.to_bytes(2, "big")
            changelist.append({"action": "insert", "key": key.hex(), "value": value.hex()})
            key = (index + key_offset).to_bytes(2, "big")
            value = (index + key_offset).to_bytes(2, "big")
            changelist.append({"action": "insert", "key": key.hex(), "value": value.hex()})
            store_updates.append({"store_id": store_id.hex(), "changelist": changelist})

        if layer == InterfaceLayer.direct:
            res = await data_rpc_api.multistore_batch_update(
                {"store_updates": store_updates, "submit_on_chain": submit_on_chain}
            )
            if submit_on_chain:
                update_tx_rec0 = res["tx_id"][0]
            else:
                assert res == {}
        elif layer == InterfaceLayer.funcs:
            res = await update_multiple_stores_cmd(
                rpc_port=rpc_port,
                store_updates=store_updates,
                submit_on_chain=submit_on_chain,
                fee=None,
                fingerprint=None,
                root_path=bt.root_path,
            )
            if submit_on_chain:
                update_tx_rec0 = bytes32.from_hexstr(res["tx_id"][0])
            else:
                assert res == {"success": True}
        elif layer == InterfaceLayer.cli:
            process = await run_cli_cmd(
                "data",
                "update_multiple_stores",
                "--store_updates",
                json.dumps(store_updates),
                "--data-rpc-port",
                str(rpc_port),
                "--submit" if submit_on_chain else "--no-submit",
                root_path=bt.root_path,
            )
            assert process.stdout is not None
            raw_output = await process.stdout.read()
            res = json.loads(raw_output)

            if submit_on_chain:
                update_tx_rec0 = bytes32.from_hexstr(res["tx_id"][0])
            else:
                assert res == {"success": True}
        elif layer == InterfaceLayer.client:
            async with DataLayerRpcClient.create_as_context(
                self_hostname=self_hostname,
                port=rpc_port,
                root_path=bt.root_path,
                net_config=bt.config,
            ) as client:
                res = await client.update_multiple_stores(
                    store_updates=store_updates,
                    submit_on_chain=submit_on_chain,
                    fee=None,
                )

            if submit_on_chain:
                update_tx_rec0 = bytes32.from_hexstr(res["tx_id"][0])
            else:
                assert res == {"success": True}
        else:  # pragma: no cover
            assert False, "unhandled parametrization"

        if not submit_on_chain:
            if layer == InterfaceLayer.direct:
                res = await data_rpc_api.submit_all_pending_roots({})
                update_tx_rec0 = res["tx_id"][0]
            elif layer == InterfaceLayer.funcs:
                res = await submit_all_pending_roots_cmd(
                    rpc_port=rpc_port,
                    fee=None,
                    fingerprint=None,
                    root_path=bt.root_path,
                )
                update_tx_rec0 = bytes32.from_hexstr(res["tx_id"][0])
            elif layer == InterfaceLayer.cli:
                process = await run_cli_cmd(
                    "data",
                    "submit_all_pending_roots",
                    "--data-rpc-port",
                    str(rpc_port),
                    root_path=bt.root_path,
                )
                assert process.stdout is not None
                raw_output = await process.stdout.read()
                res = json.loads(raw_output)
                update_tx_rec0 = bytes32.from_hexstr(res["tx_id"][0])
            elif layer == InterfaceLayer.client:
                async with DataLayerRpcClient.create_as_context(
                    self_hostname=self_hostname,
                    port=rpc_port,
                    root_path=bt.root_path,
                    net_config=bt.config,
                ) as client:
                    res = await client.submit_all_pending_roots(fee=None)

                update_tx_rec0 = bytes32.from_hexstr(res["tx_id"][0])
            else:  # pragma: no cover
                assert False, "unhandled parametrization"

        await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)

        for index, store_id in enumerate(store_ids):
            for offset in (0, 1000):
                key = (index + offset).to_bytes(2, "big")
                value = (index + offset).to_bytes(2, "big")
                res = await data_rpc_api.get_value({"id": store_id.hex(), "key": key.hex()})
                assert hexstr_to_bytes(res["value"]) == value

        with pytest.raises(Exception, match="No pending roots found to submit"):
            await data_rpc_api.submit_all_pending_roots({})
        for store_id in store_ids:
            pending_root = await data_store.get_pending_root(store_id=store_id)
            assert pending_root is None

        store_updates = []
        key = b"0000"
        value = b"0000"
        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        store_updates.append({"store_id": store_id.hex(), "changelist": changelist})
        key = b"0001"
        value = b"0001"
        changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
        store_updates.append({"store_id": store_id.hex(), "changelist": changelist})
        with pytest.raises(Exception, match=f"Store id {store_id.hex()} must appear in a single update"):
            await data_rpc_api.multistore_batch_update({"store_updates": store_updates})
        store_updates = [{"changelist": changelist}]
        with pytest.raises(Exception, match="Each update must specify a store_id"):
            await data_rpc_api.multistore_batch_update({"store_updates": store_updates})
        store_updates = [{"store_id": store_id.hex()}]
        with pytest.raises(Exception, match="Each update must specify a changelist"):
            await data_rpc_api.multistore_batch_update({"store_updates": store_updates})


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_unsubmitted_batch_db_migration(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    bt: BlockTools,
    monkeypatch: Any,
) -> None:
    with monkeypatch.context() as m:

        class OldStatus(IntEnum):
            PENDING = 1
            COMMITTED = 2
            PENDING_BATCH = 3

        class ModifiedStatus(IntEnum):
            PENDING = 1
            COMMITTED = 2

        m.setattr("chia.data_layer.data_layer_util.Status", ModifiedStatus)
        m.setattr("chia.data_layer.data_store.Status", ModifiedStatus)
        m.setattr("chia.data_layer.data_layer.Status", ModifiedStatus)

        wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
            self_hostname, one_wallet_and_one_simulator_services
        )

        async with init_data_layer_service(
            wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path
        ) as data_layer_service:
            assert data_layer_service.rpc_server is not None
            data_layer = data_layer_service._api.data_layer
            data_rpc_api = DataLayerRpcApi(data_layer)
            res = await data_rpc_api.create_data_store({})
            assert res is not None

            store_id = bytes32.from_hexstr(res["id"])
            await farm_block_check_singleton(data_layer, full_node_api, ph, store_id, wallet=wallet_rpc_api.service)

            m.setattr("chia.data_layer.data_layer_util.Status", OldStatus)
            m.setattr("chia.data_layer.data_store.Status", OldStatus)
            m.setattr("chia.data_layer.data_layer.Status", OldStatus)

            key = b"0000"
            value = b"0000"
            changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
            res = await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist})
            update_tx_rec0 = res["tx_id"]
            await farm_block_with_spend(full_node_api, ph, update_tx_rec0, wallet_rpc_api)
            keys = await data_rpc_api.get_keys({"id": store_id.hex()})
            assert keys == {"keys": ["0x30303030"]}

            key = b"0001"
            value = b"0001"
            changelist = [{"action": "insert", "key": key.hex(), "value": value.hex()}]
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed: status == 1 OR status == 2"):
                await data_rpc_api.batch_update(
                    {"id": store_id.hex(), "changelist": changelist, "submit_on_chain": False}
                )

    async with init_data_layer_service(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer_service:
        assert data_layer_service.rpc_server is not None
        data_layer = data_layer_service._api.data_layer
        data_rpc_api = DataLayerRpcApi(data_layer)
        # Test we don't migrate twice.
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed: status == 1 OR status == 2"):
            await data_rpc_api.batch_update({"id": store_id.hex(), "changelist": changelist, "submit_on_chain": False})

    # Artificially remove the first migration.
    async with DataStore.managed(database=tmp_path.joinpath("db.sqlite")) as data_store:
        async with data_store.db_wrapper.writer() as writer:
            await writer.execute("DELETE FROM schema")

    async with init_data_layer_service(wallet_rpc_port=wallet_rpc_port, bt=bt, db_path=tmp_path) as data_layer_service:
        assert data_layer_service.rpc_server is not None
        data_layer = data_layer_service._api.data_layer
        data_rpc_api = DataLayerRpcApi(data_layer)
        res = await data_rpc_api.batch_update(
            {"id": store_id.hex(), "changelist": changelist, "submit_on_chain": False}
        )
        assert res == {}

        res = await data_rpc_api.submit_pending_root({"id": store_id.hex()})
        update_tx_rec1 = res["tx_id"]
        await farm_block_with_spend(full_node_api, ph, update_tx_rec1, wallet_rpc_api)
        keys = await data_rpc_api.get_keys({"id": store_id.hex()})
        assert keys == {"keys": ["0x30303031", "0x30303030"]}


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@boolean_datacases(name="auto_subscribe_to_local_stores", false="do not auto subscribe", true="auto subscribe")
@pytest.mark.anyio
async def test_auto_subscribe_to_local_stores(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    monkeypatch: Any,
    auto_subscribe_to_local_stores: bool,
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    manage_data_interval = 5
    fake_store = bytes32([1] * 32)

    async def mock_get_store_ids(self: Any) -> Set[bytes32]:
        return {fake_store}

    async def mock_dl_track_new(self: Any, request: Dict[str, Any]) -> Dict[str, Any]:
        # ignore and just return empty response
        return {}

    with monkeypatch.context() as m:
        m.setattr("chia.data_layer.data_store.DataStore.get_store_ids", mock_get_store_ids)
        m.setattr("chia.rpc.wallet_rpc_client.WalletRpcClient.dl_track_new", mock_dl_track_new)

        config = bt.config
        config["data_layer"]["auto_subscribe_to_local_stores"] = auto_subscribe_to_local_stores
        bt.change_config(new_config=config)

        async with init_data_layer(
            wallet_rpc_port=wallet_rpc_port,
            bt=bt,
            db_path=tmp_path,
            manage_data_interval=manage_data_interval,
            maximum_full_file_count=100,
        ) as data_layer:
            data_rpc_api = DataLayerRpcApi(data_layer)

            await asyncio.sleep(manage_data_interval)

            response = await data_rpc_api.subscriptions(request={})

            if auto_subscribe_to_local_stores:
                assert fake_store.hex() in response["store_ids"]
            else:
                assert fake_store.hex() not in response["store_ids"]


@pytest.mark.limit_consensus_modes(reason="does not depend on consensus rules")
@pytest.mark.anyio
async def test_local_store_exception(
    self_hostname: str,
    one_wallet_and_one_simulator_services: SimulatorsAndWalletsServices,
    tmp_path: Path,
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wallet_rpc_api, full_node_api, wallet_rpc_port, ph, bt = await init_wallet_and_node(
        self_hostname, one_wallet_and_one_simulator_services
    )
    manage_data_interval = 5
    fake_store = bytes32([1] * 32)

    async def mock_get_store_ids(self: Any) -> Set[bytes32]:
        return {fake_store}

    with monkeypatch.context() as m, caplog.at_level(logging.INFO):
        m.setattr("chia.data_layer.data_store.DataStore.get_store_ids", mock_get_store_ids)

        config = bt.config
        config["data_layer"]["auto_subscribe_to_local_stores"] = True
        bt.change_config(new_config=config)

        async with init_data_layer(
            wallet_rpc_port=wallet_rpc_port,
            bt=bt,
            db_path=tmp_path,
            manage_data_interval=manage_data_interval,
            maximum_full_file_count=100,
        ):
            await asyncio.sleep(manage_data_interval)

            assert f"Can't subscribe to local store {fake_store.hex()}:" in caplog.text
