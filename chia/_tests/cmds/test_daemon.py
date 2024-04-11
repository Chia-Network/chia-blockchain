from __future__ import annotations

from typing import Any

import pytest
from pytest_mock import MockerFixture

from chia.cmds.start_funcs import create_start_daemon_connection
from chia.simulator.block_tools import BlockTools


@pytest.mark.anyio
@pytest.mark.parametrize("skip_keyring", [False, True])
async def test_daemon(skip_keyring: bool, mocker: MockerFixture, bt: BlockTools, capsys: Any) -> None:
    mocker.patch("sys.argv", ["chia", "start", "daemon"])
    daemon = await create_start_daemon_connection(bt.root_path, bt.config, skip_keyring)
    assert daemon is not None
    captured = capsys.readouterr()
    assert captured.err == ""
    if skip_keyring:
        assert captured.out == "Daemon not started yet\nStarting daemon\nSkipping to unlock keyring\n"
    else:
        assert captured.out == "Daemon not started yet\nStarting daemon\n"
