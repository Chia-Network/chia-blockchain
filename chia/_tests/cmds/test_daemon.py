from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
from _pytest.capture import CaptureFixture
from pytest_mock import MockerFixture

from chia.cmds.start_funcs import create_start_daemon_connection
from chia.simulator.block_tools import BlockTools


@pytest.mark.anyio
@pytest.mark.parametrize("skip_keyring", [False, True])
async def test_daemon(skip_keyring: bool, mocker: MockerFixture, bt: BlockTools, capsys: CaptureFixture[str]) -> None:
    class DummyConnection:
        @staticmethod
        async def is_keyring_locked() -> bool:
            return False

        @staticmethod
        async def unlock_keyring() -> None:
            return None

    async def connect_to_daemon_and_validate(_root_path: Path, _config: Dict[str, Any]) -> DummyConnection:
        return DummyConnection()

    mocker.patch("chia.cmds.start_funcs.connect_to_daemon_and_validate", side_effect=connect_to_daemon_and_validate)

    daemon = await create_start_daemon_connection(bt.root_path, bt.config, skip_keyring=skip_keyring)
    assert daemon is not None
    captured = capsys.readouterr()
    assert captured.err == ""
    if skip_keyring:
        assert captured.out.endswith("Skipping to unlock keyring\n")
    else:
        assert not captured.out.endswith("Skipping to unlock keyring\n")
