#!/usr/bin/env python3

from __future__ import annotations

import enum
import os
import pathlib
import subprocess
import sys

here = pathlib.Path(__file__).parent.absolute()


class Env(enum.Enum):
    chia = ".venv"
    poetry = ".penv"


def main(*args: str) -> int:
    if len(args) == 0:
        print("Parameters required")
        return 1

    env = Env.chia
    if args[0].startswith("--"):
        env = Env[args[0][2:]]
        args = args[1:]

    if sys.platform == "win32":
        script = "activated.ps1"
        command = ["powershell", os.fspath(here.joinpath(script)), env.value, *args]
    else:
        script = "activated.sh"
        command = ["sh", os.fspath(here.joinpath(script)), env.value, *args]

    completed_process = subprocess.run(command)

    return completed_process.returncode


sys.exit(main(*sys.argv[1:]))
