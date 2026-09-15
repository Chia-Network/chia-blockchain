from __future__ import annotations

import sys
from pathlib import Path

import pytest

from chia.ssl.create_ssl import create_all_ssl, get_mozilla_ca_crt
from chia.ssl.ssl_check import check_ssl


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


@pytest.mark.skipif(sys.platform == "win32", reason="SSL permission checks are not enforced on Windows")
def test_check_ssl_ignores_bundled_mozilla_ca_permissions(
    capsys: pytest.CaptureFixture[str],
    root_path_populated_with_config: Path,
) -> None:
    mozilla_ca = Path(get_mozilla_ca_crt())
    original_mode = mozilla_ca.stat().st_mode & 0o777

    with capsys.disabled():
        create_all_ssl(root_path=root_path_populated_with_config)
        mozilla_ca.chmod(mode=0o664)

    try:
        check_ssl(root_path=root_path_populated_with_config)

        with capsys.disabled():
            captured = capsys.readouterr()

            assert captured.out == ""
            assert "cacert.pem" not in captured.err
            assert "WARNING: UNPROTECTED SSL FILE!" not in captured.err
    finally:
        mozilla_ca.chmod(mode=original_mode)
