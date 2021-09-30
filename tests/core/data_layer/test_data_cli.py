import contextlib
from dataclasses import dataclass
import json
import os
import pathlib
import subprocess
import sys
import sysconfig
import time

import pytest


scripts_path = pathlib.Path(sysconfig.get_path("scripts"))


@dataclass
class ChiaRoot:
    path: pathlib.Path

    def run(
        self, args, *other_args, check=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
    ):
        # TODO: --root-path doesn't seem to work here...
        kwargs.setdefault("env", {})
        kwargs["env"]["CHIA_ROOT"] = os.fspath(self.path)

        modified_args = [scripts_path.joinpath("chia"), "--root-path", self.path, *args]
        modified_args = [os.fspath(element) for element in modified_args]
        other_args = [modified_args, *other_args]

        kwargs["check"] = check
        kwargs["encoding"] = encoding
        kwargs["stdout"] = stdout
        kwargs["stderr"] = stderr

        return subprocess.run(*other_args, **kwargs)


@pytest.fixture(name="chia_root", scope="function")
def chia_root_fixture(tmp_path: pathlib.Path) -> ChiaRoot:
    root = ChiaRoot(path=tmp_path.joinpath("chia_root"))
    root.run(args=["init"])

    return root


@contextlib.contextmanager
def closing_chia_root_popen(chia_root: ChiaRoot, args):
    environment = {**os.environ, "CHIA_ROOT": os.fspath(chia_root.path)}

    with subprocess.Popen(args=args, env=environment) as process:
        try:
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except TimeoutError:
                process.kill()


@pytest.fixture(name="chia_daemon", scope="function")
def chia_daemon_fixture(chia_root: ChiaRoot) -> None:
    with closing_chia_root_popen(chia_root=chia_root, args=[sys.executable, "-m", "chia.daemon.server"]):
        # TODO: this is not pretty as a hard coded time
        # let it settle
        time.sleep(5)
        yield


@pytest.fixture(name="chia_data", scope="function")
def chia_data_fixture(chia_root: ChiaRoot, chia_daemon: None) -> None:
    with closing_chia_root_popen(chia_root=chia_root, args=[os.fspath(scripts_path.joinpath("chia_data_layer"))]):
        # TODO: this is not pretty as a hard coded time
        # let it settle
        time.sleep(5)
        yield


@pytest.mark.asyncio
async def test_help(chia_root):
    """Just a trivial test to make sure the subprocessing is at least working and the
    data executable does run.
    """
    completed_process = chia_root.run(args=["data", "--help"])
    assert "Show this message and exit" in completed_process.stdout


def test_round_trip(chia_root, chia_daemon: None, chia_data: None):
    """Create a table, insert a row, get the row by its hash."""

    table = "0102030405060708091011121314151617181920212223242526272829303132"
    row_data = "ffff8353594d8083616263"
    row_hash = "1a6f915513173902a7216e7d9e4a16bfd088e20683f45de3b432ce72e9cc7aa8"

    chia_root.run(args=["data", "create_table", "--table_name", "test table", "--table", table])
    chia_root.run(args=["data", "insert_row", "--table", table, "--row_data", row_data])
    completed_process = chia_root.run(args=["data", "get_row", "--table", table, "--row_hash", row_hash])

    parsed = json.loads(completed_process.stdout)
    expected = {"row_data": row_data, "row_hash": row_hash, "success": True}

    assert parsed == expected
