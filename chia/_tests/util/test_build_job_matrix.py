from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

import chia._tests

build_job_matrix_path = pathlib.Path(chia._tests.__file__).with_name("build-job-matrix.py")


def run(args: list[str], script_path: pathlib.Path = build_job_matrix_path) -> str:
    completed_process = subprocess.run(
        [sys.executable, script_path, *args],
        check=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    )
    return completed_process.stdout


@pytest.mark.parametrize("per", ["directory", "file"])
@pytest.mark.parametrize("checkout_directory", ["work", "_work", ".work"])
def test_checkout_path(tmp_path: pathlib.Path, per: str, checkout_directory: str) -> None:
    test_root = tmp_path / checkout_directory / "chia" / "_tests"
    test_root.mkdir(parents=True)
    script_path = test_root / build_job_matrix_path.name
    shutil.copyfile(build_job_matrix_path, script_path)
    shutil.copyfile(build_job_matrix_path.with_name("testconfig.py"), test_root / "testconfig.py")
    for directory in ["example", "_excluded", ".excluded"]:
        test_directory = test_root / directory
        test_directory.mkdir()
        (test_directory / "test_example.py").touch()

    matrix = json.loads(run(args=["--per", per], script_path=script_path))

    expected_name = "example" if per == "directory" else "example.test_example"
    assert [entry["name"] for entry in matrix] == [expected_name]


def test() -> None:
    timeouts: dict[int, dict[str, int]] = {}

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
