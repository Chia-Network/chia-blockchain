from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Dict, List

import chia._tests

build_job_matrix_path = pathlib.Path(chia._tests.__file__).with_name("build-job-matrix.py")


def run(args: List[str]) -> str:
    completed_process = subprocess.run(
        [sys.executable, build_job_matrix_path, *args],
        check=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    )
    return completed_process.stdout


def test() -> None:
    timeouts: Dict[int, Dict[str, int]] = {}

    multipliers = [1, 2, 3]

    for multiplier in multipliers:
        timeouts[multiplier] = {}
        output = run(args=["--per", "directory", "--timeout-multiplier", str(multiplier)])
        matrix = json.loads(output)
        for entry in matrix:
            timeouts[multiplier][entry["name"]] = entry["job_timeout"]

    reference = timeouts[1]

    for multiplier in multipliers:
        if multiplier == 1:
            continue

        adjusted_reference = {key: value * multiplier for key, value in reference.items()}
        assert timeouts[multiplier] == adjusted_reference
