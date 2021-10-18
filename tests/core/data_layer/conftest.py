import contextlib
import os
import pathlib
import subprocess
import sys
import sysconfig
import time
from typing import Iterator, List

import pytest

from tests.core.data_layer.util import ChiaRoot


# TODO: These are more general than the data layer and should either move elsewhere or
#       be replaced with an existing common approach.  For now they can at least be
#       shared among the data layer test files.


@pytest.fixture(name="scripts_path", scope="session")
def scripts_path_fixture():
    scripts_string = sysconfig.get_path("scripts")
    if scripts_string is None:
        raise Exception("These tests depend on the scripts path existing")

    return pathlib.Path(scripts_string)


@pytest.fixture(name="chia_root", scope="function")
def chia_root_fixture(tmp_path: pathlib.Path, scripts_path: pathlib.Path) -> ChiaRoot:
    root = ChiaRoot(path=tmp_path.joinpath("chia_root"), scripts_path=scripts_path)
    root.run(args=["init"])
    root.run(args=["configure", "--set-log-level", "INFO"])

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
def chia_data_fixture(chia_root: ChiaRoot, chia_daemon: None, scripts_path: pathlib.Path) -> Iterator[None]:
    with closing_chia_root_popen(chia_root=chia_root, args=[os.fspath(scripts_path.joinpath("chia_data_layer"))]):
        # TODO: this is not pretty as a hard coded time
        # let it settle
        time.sleep(5)
        yield
