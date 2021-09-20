import asyncio
import traceback
import subprocess
import os
import logging
import sys

from pathlib import Path
from typing import Any, Dict, Optional
from chia.plotting.create_plots import resolve_plot_keys

log = logging.getLogger(__name__)


MADMAX_PLOTTER_DIR = "madmax-plotter"


def is_madmax_supported() -> bool:
    return sys.platform.startswith("linux") or sys.platform.startswith("darwin")


def get_madmax_install_path(plotters_root_path: Path) -> Path:
    return plotters_root_path / MADMAX_PLOTTER_DIR


def get_madmax_executable_path(plotters_root_path: Path) -> Path:
    return get_madmax_install_path(plotters_root_path) / "build/chia_plot"


def get_madmax_install_info(plotters_root_path: Path) -> Optional[Dict[str, Any]]:
    info: Dict[str, Any] = {"display_name": "madMAx Plotter"}
    installed: bool = False
    supported: bool = is_madmax_supported()

    if get_madmax_executable_path(plotters_root_path).exists():
        installed = True
        # TODO: Figure out how to get madmax version

    info["installed"] = installed
    if installed is False:
        info["can_install"] = supported

    return info


def install_madmax(plotters_root_path: Path):
    if is_madmax_supported():
        print("Installing dependencies.")
        if sys.platform.startswith("linux"):
            try:
                subprocess.run(
                    [
                        "sudo",
                        "apt",
                        "install",
                        "-y",
                        "libsodium-dev",
                        "cmake",
                        "g++",
                        "git",
                        "build-essential",
                    ]
                )
            except Exception as e:
                raise ValueError(f"Could not install dependencies. {e}")
        if sys.platform.startswith("darwin"):
            try:
                subprocess.run(
                    [
                        "brew",
                        "install",
                        "libsodium",
                        "cmake",
                        "git",
                        "autoconf",
                        "automake",
                        "libtool",
                        "wget",
                    ]
                )
                subprocess.run(["brew", "link", "cmake"])
            except Exception as e:
                raise ValueError(f"Could not install dependencies. {e}")

        try:
            subprocess.run(["git", "--version"])
        except FileNotFoundError as e:
            raise ValueError(f"Git not installed. Aborting madmax install. {e}")

        print("Cloning git repository.")
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "https://github.com/Chia-Network/chia-plotter-madmax.git",
                    MADMAX_PLOTTER_DIR,
                ],
                cwd=os.fspath(plotters_root_path),
            )
        except Exception as e:
            raise ValueError(f"Could not clone madmax repository. {e}")

        print("Installing git submodules.")
        madmax_path: str = os.fspath(get_madmax_install_path(plotters_root_path))
        try:
            subprocess.run(["git", "submodule", "update", "--init", "--recursive"], cwd=madmax_path)
        except Exception as e:
            raise ValueError(f"Could not install git submodules. {e}")

        print("Running install script.")
        try:
            subprocess.run(["./make_devel.sh"], cwd=madmax_path)
        except Exception as e:
            raise ValueError(f"Install script failed. {e}")
    else:
        raise ValueError("Platform not supported yet for madmax plotter.")


progress = {
    "[P1] Table 1 took": 0.01,
    "[P1] Table 2 took": 0.06,
    "[P1] Table 3 took": 0.12,
    "[P1] Table 4 took": 0.2,
    "[P1] Table 5 took": 0.28,
    "[P1] Table 6 took": 0.36,
    "[P1] Table 7 took": 0.42,
    "[P2] Table 7 rewrite took": 0.43,
    "[P2] Table 6 rewrite took": 0.48,
    "[P2] Table 5 rewrite took": 0.51,
    "[P2] Table 4 rewrite took": 0.55,
    "[P2] Table 3 rewrite took": 0.58,
    "[P2] Table 2 rewrite took": 0.61,
    "[P3-2] Table 2 took": 0.66,
    "[P3-2] Table 3 took": 0.73,
    "[P3-2] Table 4 took": 0.79,
    "[P3-2] Table 5 took": 0.85,
    "[P3-2] Table 6 took": 0.92,
    "[P3-2] Table 7 took": 0.98,
}


# https://kevinmccarthy.org/2016/07/25/streaming-subprocess-stdin-and-stdout-with-asyncio-in-python/
async def _read_stream(stream, callback):
    while True:
        line = await stream.readline()
        if line:
            callback(line)
        else:
            break


def parse_stdout(out):
    out = out.rstrip()
    print(out)
    for k, v in progress.items():
        if k in out:
            print(f"Progress update: {v}")


async def run(command):
    process = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    await asyncio.wait(
        [
            _read_stream(
                process.stdout,
                lambda x: parse_stdout(x.decode("UTF8")),
            ),
            _read_stream(
                process.stderr,
                lambda x: print("STDERR: {}".format(x.decode("UTF8"))),
            ),
        ]
    )

    await process.wait()


async def run_madmax(args):
    cmd = ""
    for arg in args:
        cmd += arg
        cmd += " "
    print(f"Running command: {cmd[:-1]}")
    await run(cmd[:-1])


def plot_madmax(args, chia_root_path: Path, plotters_root_path: Path):
    if not os.path.exists(get_madmax_executable_path(plotters_root_path)):
        print("Installing madmax plotter.")
        try:
            install_madmax(plotters_root_path)
        except Exception as e:
            print(f"Exception while installing madmax plotter: {e}")
            return
    plot_keys = asyncio.get_event_loop().run_until_complete(
        resolve_plot_keys(
            None if args.farmerkey == b"" else args.farmerkey.hex(),
            None,
            None if args.pool_key == b"" else args.pool_key.hex(),
            None if args.contract == "" else args.contract,
            chia_root_path,
            log,
            False,  # args.connect_to_daemon,
        )
    )
    call_args = []
    call_args.append(os.fspath(get_madmax_executable_path(plotters_root_path)))
    call_args.append("-f")
    call_args.append(bytes(plot_keys.farmer_public_key).hex())
    if plot_keys.pool_public_key is not None:
        call_args.append("-p")
        call_args.append(bytes(plot_keys.pool_public_key).hex())
    call_args.append("-t")
    call_args.append(args.tmpdir)
    call_args.append("-2")
    call_args.append(args.tmpdir2)
    call_args.append("-d")
    call_args.append(args.finaldir)
    if plot_keys.pool_contract_address is not None:
        call_args.append("-c")
        call_args.append(plot_keys.pool_contract_address)
    call_args.append("-n")
    call_args.append(str(args.count))
    call_args.append("-r")
    call_args.append(str(args.threads))
    call_args.append("-u")
    call_args.append(str(args.buckets))
    call_args.append("-v")
    call_args.append(str(args.buckets3))
    call_args.append("-w")
    call_args.append(str(int(args.waitforcopy)))
    call_args.append("-K")
    call_args.append(str(args.rmulti2))
    if args.size != 32:
        call_args.append("-k")
        call_args.append(str(args.size))
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_madmax(call_args))
    except Exception as e:
        print(f"Exception while plotting: {type(e)} {e}")
        print(f"Traceback: {traceback.format_exc()}")
