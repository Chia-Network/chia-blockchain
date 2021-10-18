import contextlib
import json
import os
import pathlib
import subprocess
import sys
import sysconfig
import time
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Any, Dict, Iterator, List, Optional, Union

import aiosqlite
import pytest

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_store import DataStore
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.types.blockchain_format.program import Program
from chia.util.db_wrapper import DBWrapper
from chia.util.default_root import DEFAULT_ROOT_PATH
from tests.block_tools import create_block_tools_async

from tests.core.data_layer.util import ChiaRoot


@pytest.mark.asyncio
async def test_help(chia_root: ChiaRoot) -> None:
    """Just a trivial test to make sure the subprocessing is at least working and the
    data executable does run.
    """
    completed_process = chia_root.run(args=["data", "--help"])
    assert "Show this message and exit" in completed_process.stdout


@pytest.mark.xfail(strict=True)
@pytest.mark.asyncio
def test_round_trip(chia_root: ChiaRoot, chia_daemon: None, chia_data: None) -> None:
    """Create a table, insert a row, get the row by its hash."""

    with chia_root.print_log_after():
        row_data = "ffff8353594d8083616263"
        row_hash = "1a6f915513173902a7216e7d9e4a16bfd088e20683f45de3b432ce72e9cc7aa8"

        changelist: List[Dict[str, str]] = [{"action": "insert", "row_data": row_data}]

        create = chia_root.run(args=["data", "create_table", "--table", "test table"])
        print(f"create {create}")
        # TODO get store id from cli response
        store_id = "0102030405060708091011121314151617181920212223242526272829303132"
        update = chia_root.run(
            args=["data", "update_table", "--table", store_id, "--changelist", json.dumps(changelist)]
        )
        print(f"update {update}")
        completed_process = chia_root.run(args=["data", "get_row", "--table", store_id, "--row_hash", row_hash])
        parsed = json.loads(completed_process.stdout)
        expected = {"row_data": row_data, "row_hash": row_hash, "success": True}

        assert parsed == expected


# todo tmp test
@pytest.mark.asyncio
# @pytest.mark.skip("tmp test")
async def test_create() -> None:
    """Create a table, insert a row, get the row by its hash."""
    root = DEFAULT_ROOT_PATH
    bt = await create_block_tools_async()
    config = bt.config
    config["database_path"] = "data_layer_test"
    data_layer = DataLayer(config, root_path=root, consensus_constants=DEFAULT_CONSTANTS)
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
    await rpc_api.get_value({"id": tree_id, "key": key.as_bin()})
    return
