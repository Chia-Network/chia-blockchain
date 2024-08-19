from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from _pytest.capture import CaptureFixture
from click.testing import CliRunner
from pytest_mock import MockerFixture

from chia.cmds.chia import cli
from chia.cmds.start_funcs import create_start_daemon_connection, launch_start_daemon


@pytest.mark.anyio
@pytest.mark.parametrize("skip_keyring", [False, True])
@pytest.mark.parametrize("unlock_keyring", [False, True])
async def test_daemon(
    skip_keyring: bool, unlock_keyring: bool, mocker: MockerFixture, capsys: CaptureFixture[str]
) -> None:
    class DummyConnection:
        @staticmethod
        async def is_keyring_locked() -> bool:
            return unlock_keyring

        @staticmethod
        async def unlock_keyring(_passphrase: str) -> bool:
            return True

    async def connect_to_daemon_and_validate(_root_path: Path, _config: Dict[str, Any]) -> DummyConnection:
        return DummyConnection()

    class DummyKeychain:
        @staticmethod
        def get_cached_master_passphrase() -> Optional[str]:
            return None

    def get_current_passphrase() -> Optional[str]:
        return "a-passphrase"

    mocker.patch("chia.cmds.start_funcs.connect_to_daemon_and_validate", side_effect=connect_to_daemon_and_validate)
    mocker.patch("chia.cmds.start_funcs.Keychain", new=DummyKeychain)
    mocker.patch("chia.cmds.start_funcs.get_current_passphrase", side_effect=get_current_passphrase)

    daemon = await create_start_daemon_connection(Path("/path-not-exist"), {}, skip_keyring=skip_keyring)
    assert daemon is not None
    captured = capsys.readouterr()
    assert captured.err == ""
    if skip_keyring:
        assert captured.out.endswith("Skipping to unlock keyring\n")
    else:
        assert not captured.out.endswith("Skipping to unlock keyring\n")


@pytest.mark.anyio
def test_launch_start_daemon(tmp_path: Path) -> None:
    sys.argv[0] = "not-exist"
    with pytest.raises(FileNotFoundError):
        launch_start_daemon(tmp_path)

    helper: Path = Path(sys.executable)
    sys.argv[0] = str(helper.parent) + "/chia"
    process = launch_start_daemon(tmp_path)
    assert process is not None
    process.kill()
    process.wait()


def test_start_daemon(tmp_path: Path, empty_keyring: Any, mocker: MockerFixture) -> None:
    class DummyDaemon:
        @staticmethod
        async def close() -> None:
            return None

    async def create_start_daemon_connection_dummy(
        root_path: Path, config: Dict[str, Any], *, skip_keyring: bool
    ) -> DummyDaemon:
        return DummyDaemon()

    mocker.patch(
        "chia.cmds.start_funcs.create_start_daemon_connection", side_effect=create_start_daemon_connection_dummy
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--root-path", str(tmp_path), "init"],
    )
    assert result.exit_code == 0
    result = runner.invoke(cli, ["--root-path", str(tmp_path), "start", "daemon", "-s"])
    assert result.exit_code == 0
