from __future__ import annotations

import asyncio
import json
import signal
import sys
import time
from typing import Dict, List

import aiohttp.client_exceptions
import pytest

from chia.cmds.data_funcs import get_client
from chia.simulator.socket import find_available_listen_port
from chia.util.config import lock_and_load_config, save_config
from chia.util.misc import termination_signals
from tests.core.data_layer.util import ChiaRoot
from tests.util.misc import closing_chia_root_popen

pytestmark = pytest.mark.data_layer


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
        create = chia_root.run(args=["data", "create_data_store"])
        print(f"create_data_store: {create}")
        dic = json.loads(create.stdout)
        assert dic["success"]
        tree_id = dic["id"]
        key = "1a6f915513173902a7216e7d9e4a16bfd088e20683f45de3b432ce72e9cc7aa8"
        value = "ffff8353594d8083616263"
        changelist: List[Dict[str, str]] = [{"action": "insert", "key": key, "value": value}]
        print(json.dumps(changelist))
        update = chia_root.run(
            args=["data", "update_data_store", "--id", tree_id, "--changelist", json.dumps(changelist)]
        )
        dic = json.loads(create.stdout)
        assert dic["success"]
        print(f"update_data_store: {update}")
        completed_process = chia_root.run(args=["data", "get_value", "--id", tree_id, "--key", key])
        parsed = json.loads(completed_process.stdout)
        expected = {"value": value, "success": True}
        assert parsed == expected
        get_keys_values = chia_root.run(args=["data", "get_keys_values", "--id", tree_id])
        print(f"get_keys_values: {get_keys_values}")
        changelist = [{"action": "delete", "key": key}]
        update = chia_root.run(
            args=["data", "update_data_store", "--id", tree_id, "--changelist", json.dumps(changelist)]
        )
        print(f"update_data_store: {update}")
        completed_process = chia_root.run(args=["data", "get_value", "--id", tree_id, "--key", key])
        parsed = json.loads(completed_process.stdout)
        expected = {"data": None, "success": True}
        assert parsed == expected


@pytest.mark.parametrize(argnames="signal_number", argvalues=termination_signals)
@pytest.mark.asyncio
async def test_data_layer_terminates(signal_number: signal.Signals, chia_root: ChiaRoot) -> None:
    port = find_available_listen_port()
    rpc_port = find_available_listen_port()
    with lock_and_load_config(root_path=chia_root.path, filename="config.yaml") as config:
        config["data_layer"]["port"] = port
        config["data_layer"]["rpc_port"] = rpc_port
        save_config(root_path=chia_root.path, filename="config.yaml", config_data=config)

    with closing_chia_root_popen(
        chia_root=chia_root,
        args=[sys.executable, "-m", "chia.server.start_data_layer"],
    ) as process:
        async with get_client(rpc_port=rpc_port, root_path=chia_root.path) as [client, _]:
            start = time.monotonic()
            while time.monotonic() - start < 15:
                try:
                    result = await client.healthz()
                except aiohttp.client_exceptions.ClientConnectorError:
                    pass
                else:
                    if result.get("success", False):
                        break

                await asyncio.sleep(0.1)
            else:
                raise Exception("unable to connect")

            return_code = process.poll()
            assert return_code is None

            process.send_signal(sig=signal_number)
            process.communicate(timeout=5)
