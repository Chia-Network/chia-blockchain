from __future__ import annotations

import json
import subprocess
import tempfile
from typing import Dict, List, Optional

import click
import packaging.version


def check_plotter(plotter: List[str], expected_output: bytes, specify_tmp: bool = True) -> None:
    with tempfile.TemporaryDirectory() as path:
        tmp_dir = []
        if specify_tmp:
            tmp_dir = ["--tmp_dir", path]
        process = subprocess.Popen(
            ["chia", "plotters", *plotter, *tmp_dir, "--final_dir", path],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        out: Optional[bytes]
        err: Optional[bytes]
        try:
            out, err = process.communicate(timeout=2)
        except subprocess.TimeoutExpired as e:
            err = e.stderr
            out = e.stdout
        else:
            print(repr(err))
            print(repr(out))
            assert False, "expected to time out"
        finally:
            process.kill()
            process.communicate()

        assert err is None, repr(err)
        assert out is not None
        assert out.startswith(expected_output), repr(out)


@click.group("installers", help="Installer related helpers such as installer testing")
def installers_group() -> None:
    pass


@installers_group.command(name="test")
@click.option("--expected-chia-version", "expected_chia_version_str", required=True)
def test_command(expected_chia_version_str: str) -> None:
    expected_chia_version = packaging.version.Version(expected_chia_version_str)

    chia_version_process = subprocess.run(
        ["chia", "version"],
        capture_output=True,
        encoding="utf-8",
    )
    assert chia_version_process.returncode == 0
    assert chia_version_process.stderr == ""

    chia_version = packaging.version.Version(chia_version_process.stdout)
    print(chia_version)
    assert chia_version == expected_chia_version, f"{chia_version} != {expected_chia_version}"

    plotter_version_process = subprocess.run(
        ["chia", "plotters", "version"],
        capture_output=True,
        encoding="utf-8",
    )
    assert plotter_version_process.returncode == 0
    assert plotter_version_process.stderr == ""

    plotter_versions: Dict[str, packaging.version.Version] = {}
    for line in plotter_version_process.stdout.splitlines():
        plotter, version = (segment.strip() for segment in line.split(":", maxsplit=1))
        plotter_versions[plotter] = packaging.version.Version(version)

    print(json.dumps({plotter: str(version) for plotter, version in plotter_versions.items()}, indent=4))
    assert {"chiapos", "madmax", "bladebit"} == plotter_versions.keys()

    # TODO: figure out a better test, these actually start plots which can use up disk
    #       space too fast

    # check_plotter(plotter=["chiapos"], expected_output=b"\nStarting plotting progress")
    # check_plotter(plotter=["madmax"], expected_output=b"Multi-threaded pipelined Chia")
    # check_plotter(plotter=["bladebit", "diskplot", "--compress", "0"], expected_output=b"\nBladebit Chia Plotter")
    # check_plotter(plotter=["bladebit", "cudaplot", "--compress", "0"], expected_output=b"\nBladebit Chia Plotter")
    # check_plotter(
    #     plotter=["bladebit", "ramplot", "--compress", "0"],
    #     expected_output=b"\nBladebit Chia Plotter",
    #     specify_tmp_dir=False,
    # )
