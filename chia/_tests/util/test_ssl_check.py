from __future__ import annotations

import sys
from pathlib import Path

import pytest

from chia.ssl.create_ssl import create_all_ssl
from chia.util.ssl_check import check_ssl


def test_check_ssl_stream_with_bad_permissions(
    capsys: pytest.CaptureFixture[str],
    root_path_populated_with_config: Path,
) -> None:
    with capsys.disabled():
        create_all_ssl(root_path=root_path_populated_with_config)
        root_path_populated_with_config.joinpath("config", "ssl", "daemon", "private_daemon.crt").chmod(mode=0o777)

    check_ssl(root_path=root_path_populated_with_config)

    with capsys.disabled():
        captured = capsys.readouterr()
        print(f"stdout: {captured.out!r}")
        print(f"stderr: {captured.err!r}")

        assert captured.out == ""
        if sys.platform == "win32":
            assert captured.err == ""
        else:
            assert "WARNING: UNPROTECTED SSL FILE!" in captured.err
