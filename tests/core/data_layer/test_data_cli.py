import contextlib
from dataclasses import dataclass
import json
import os
import pathlib
import subprocess
import sys
import sysconfig
import time
from typing import Any, IO, Iterator, List, Optional, Union, Dict, TYPE_CHECKING

import pytest

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_store import DataStore
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.types.blockchain_format.program import Program
from chia.util.db_wrapper import DBWrapper
from chia.util.default_root import DEFAULT_ROOT_PATH
from tests.block_tools import create_block_tools_async
import aiosqlite

scripts_string = sysconfig.get_path("scripts")
if scripts_string is None:
    raise Exception("These tests depend on the scripts path existing")
scripts_path = pathlib.Path(scripts_string)


# from subprocess.pyi
_FILE = Union[None, int, IO[Any]]


if TYPE_CHECKING:
    # these require Python 3.9 at runtime
    os_PathLike_str = os.PathLike[str]
    subprocess_CompletedProcess_str = subprocess.CompletedProcess[str]
else:
    os_PathLike_str = os.PathLike
    subprocess_CompletedProcess_str = subprocess.CompletedProcess


@dataclass
class ChiaRoot:
    path: pathlib.Path

    def run(
        self,
        args: List[Union[str, os_PathLike_str]],
        *other_args: Any,
        check: bool = True,
        encoding: str = "utf-8",
        stdout: Optional[_FILE] = subprocess.PIPE,
        stderr: Optional[_FILE] = subprocess.PIPE,
        **kwargs: Any,
    ) -> subprocess_CompletedProcess_str:
        # TODO: --root-path doesn't seem to work here...
        kwargs.setdefault("env", {})
        kwargs["env"]["CHIA_ROOT"] = os.fspath(self.path)

        modified_args: List[Union[str, os_PathLike_str]] = [
            scripts_path.joinpath("chia"),
            "--root-path",
            self.path,
            *args,
        ]
        processed_args: List[str] = [os.fspath(element) for element in modified_args]
        final_args = [processed_args, *other_args]

        kwargs["check"] = check
        kwargs["encoding"] = encoding
        kwargs["stdout"] = stdout
        kwargs["stderr"] = stderr

        return subprocess.run(*final_args, **kwargs)

    def read_log(self) -> str:
        return self.path.joinpath("log", "debug.log").read_text(encoding="utf-8")

    def print_log(self) -> None:
        log_text: Optional[str]

        try:
            log_text = self.read_log()
        except FileNotFoundError:
            log_text = None

        if log_text is None:
            print(f"---- no log at: {self.path}")
        else:
            print(f"---- start of: {self.path}")
            print(log_text)
            print(f"---- end of: {self.path}")

    @contextlib.contextmanager
    def print_log_after(self) -> Iterator[None]:
        try:
            yield
        finally:
            self.print_log()


@pytest.fixture(name="chia_root", scope="function")
def chia_root_fixture(tmp_path: pathlib.Path) -> ChiaRoot:
    root = ChiaRoot(path=tmp_path.joinpath("chia_root"))
    root.run(args=["init"])
    root.run(args=["configure", "--set-log-level", "DEBUG"])

    return root


@contextlib.contextmanager
def closing_chia_root_popen(chia_root: ChiaRoot, args: List[str]) -> Iterator[None]:
    environment = {**os.environ, "CHIA_ROOT": os.fspath(chia_root.path)}

    with subprocess.Popen(args=args, env=environment) as process:
        try:
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


@pytest.fixture(name="chia_daemon", scope="function")
def chia_daemon_fixture(chia_root: ChiaRoot) -> Iterator[None]:
    with closing_chia_root_popen(chia_root=chia_root, args=[sys.executable, "-m", "chia.daemon.server"]):
        # TODO: this is not pretty as a hard coded time
        # let it settle
        time.sleep(5)
        yield


@pytest.fixture(name="chia_data", scope="function")
def chia_data_fixture(chia_root: ChiaRoot, chia_daemon: None) -> Iterator[None]:
    with closing_chia_root_popen(chia_root=chia_root, args=[os.fspath(scripts_path.joinpath("chia_data_layer"))]):
        # TODO: this is not pretty as a hard coded time
        # let it settle
        time.sleep(5)
        yield


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
        table = "0102030405060708091011121314151617181920212223242526272829303132"
        row_data = "ffff8353594d8083616263"
        row_hash = "1a6f915513173902a7216e7d9e4a16bfd088e20683f45de3b432ce72e9cc7aa8"

        changelist: List[Dict[str, str]] = [{"action": "insert", "row_data": row_data}]

        create = chia_root.run(args=["data", "create_table", "--table_name", "test table", "--table", table])
        print(f"create {create}")
        update = chia_root.run(args=["data", "update_table", "--table", table, "--changelist", json.dumps(changelist)])
        print(f"update {update}")
        completed_process = chia_root.run(args=["data", "get_row", "--table", table, "--row_hash", row_hash])
        parsed = json.loads(completed_process.stdout)
        expected = {"row_data": row_data, "row_hash": row_hash, "success": True}

        assert parsed == expected


# todo tmp test
@pytest.mark.asyncio
@pytest.mark.skip("tmp test")
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
    tree_id = "0102030405060708091011121314151617181920212223242526272829303132"
    key = Program.to("abc")
    value = Program.to([1, 2])
    changelist: List[Dict[str, str]] = [{"action": "insert", "key": key.as_bin(), "value": value.as_bin()}]
    # await rpc_api.create_kv_store({"id": tree_id})
    # await rpc_api.update_kv_store({"id": tree_id, "changelist": changelist})
    # await rpc_api.get_value({"id": tree_id, "key": key.as_bin()})
    return
