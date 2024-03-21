from __future__ import annotations

import sys
from unittest.mock import patch

from chia.cmds.start_funcs import get_launcher_args


def test_get_launcher_args(monkeypatch) -> None:
    with patch.object(sys, "argv", ["chia", "start", "daemon"]):
        monkeypatch.setenv("VIRTUAL_ENV", "")
        assert get_launcher_args() == ["chia", "run_daemon", "--wait-for-unlock"]

        monkeypatch.setenv("VIRTUAL_ENV", "/a/b/c")
        with patch.object(sys, "platform", "win32"):
            assert get_launcher_args() == ["/a/b/c/Scripts/python.exe", "chia", "run_daemon", "--wait-for-unlock"]

        with patch.object(sys, "platform", "cygwin"):
            assert get_launcher_args() == ["/a/b/c/Scripts/python.exe", "chia", "run_daemon", "--wait-for-unlock"]

        with patch.object(sys, "platform", "linux"):
            assert get_launcher_args() == ["/a/b/c/bin/python", "chia", "run_daemon", "--wait-for-unlock"]
