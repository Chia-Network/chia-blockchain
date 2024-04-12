from __future__ import annotations

from typing import Optional

import pytest
from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture

from chia.cmds.start_funcs import create_start_daemon_connection
from chia.simulator.block_tools import BlockTools


@pytest.mark.anyio
@pytest.mark.parametrize("skip_keyring", [False, True])
async def test_daemon(skip_keyring: bool, mocker: MockerFixture, bt: BlockTools, capsys: CaptureFixture[str]) -> None:
    mocker.patch("sys.argv", ["chia", "start", "daemon"])

    def get_current_passphrase() -> Optional[str]:
        return "some-passphrase"

    mocker.patch("chia.cmds.passphrase_funcs.get_current_passphrase", side_effect=get_current_passphrase)
    daemon = await create_start_daemon_connection(bt.root_path, bt.config, skip_keyring=skip_keyring)
    assert daemon is not None
    captured = capsys.readouterr()
    assert captured.err == ""
    if skip_keyring:
        assert captured.out.endswith("Skipping to unlock keyring\n")
    else:
        assert not captured.out.endswith("Skipping to unlock keyring\n")
