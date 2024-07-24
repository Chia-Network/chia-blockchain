from __future__ import annotations

import json
import subprocess
import tempfile
from typing import Dict, List, Optional

import click
import packaging.version

from chia.daemon.server import executable_for_service
from chia.util.timing import adjusted_timeout


def check_plotter(plotter: List[str], expected_output: bytes, specify_tmp: bool = True) -> None:
    with tempfile.TemporaryDirectory() as path:
        tmp_dir = []
        if specify_tmp:
            tmp_dir = ["--tmp_dir", path]
        process = subprocess.Popen(
            [executable_for_service("chia"), "plotters", *plotter, *tmp_dir, "--final_dir", path],
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
@click.option("--require-madmax/--require-no-madmax", "require_madmax", default=True)
def test_command(expected_chia_version_str: str, require_madmax: bool) -> None:
    print("testing installed executables")
    expected_chia_version = packaging.version.Version(expected_chia_version_str)

    args = [executable_for_service("chia"), "version"]
    print(f"launching: {args}")
    chia_version_process = subprocess.run(
        args,
        capture_output=True,
        encoding="utf-8",
        timeout=adjusted_timeout(30),
    )
    assert chia_version_process.returncode == 0
    assert chia_version_process.stderr == ""

    chia_version = packaging.version.Version(chia_version_process.stdout)
    print(chia_version)
    assert chia_version == expected_chia_version, f"{chia_version} != {expected_chia_version}"

    args = [executable_for_service("chia"), "plotters", "version"]
    print(f"launching: {args}")
    plotter_version_process = subprocess.run(
        args,
        capture_output=True,
        encoding="utf-8",
        timeout=adjusted_timeout(30),
    )

    print()
    print(plotter_version_process.stdout)
    print()
    print(plotter_version_process.stderr)
    print()

    assert plotter_version_process.returncode == 0
    assert plotter_version_process.stderr == ""

    found_start = False
    plotter_versions: Dict[str, packaging.version.Version] = {}
    for line in plotter_version_process.stdout.splitlines():
        if line.startswith("chiapos:"):
            found_start = True

        if not found_start:
            continue

        plotter, version = (segment.strip() for segment in line.split(":", maxsplit=1))
        plotter_versions[plotter] = packaging.version.Version(version)

    print(json.dumps({plotter: str(version) for plotter, version in plotter_versions.items()}, indent=4))
    expected = {"chiapos", "bladebit"}

    if require_madmax:
        expected.add("madmax")

    assert plotter_versions.keys() == expected, f"{expected=}"

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

    args = [executable_for_service("chia"), "init"]
    print(f"launching: {args}")
    subprocess.run(
        args,
        check=True,
        timeout=adjusted_timeout(30),
    )
