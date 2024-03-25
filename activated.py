#!/usr/bin/env python3

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

here = pathlib.Path(__file__).parent


def main(*args: str) -> int:
    if len(args) == 0:
        print("Parameters required")
        return 1

    if sys.platform == "win32":
        script = "activated.ps1"
        command = ["powershell", os.fspath(here.joinpath(script)), *args]
    else:
        script = "activated.sh"
        command = ["sh", os.fspath(here.joinpath(script)), *args]

    completed_process = subprocess.run(command)

    return completed_process.returncode


sys.exit(main(*sys.argv[1:]))
