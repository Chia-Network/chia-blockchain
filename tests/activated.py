#!/usr/bin/env python3

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
    else:
        script = "activated.sh"
    completed_process = subprocess.run([here.joinpath(script), *args])

    return completed_process.returncode


sys.exit(main(*sys.argv[1:]))
