import asyncio
import traceback
import subprocess
import os
import sys

from pathlib import Path
from typing import Any, Dict, Optional

BLADEBIT_PLOTTER_DIR = "bladebit"
BLADEBIT_MIN_RAM_GIBS = 416


def is_bladebit_supported() -> bool:
    return sys.platform.startswith("linux")


def meets_memory_requirement() -> bool:
    have_enough_memory: bool = False
    try:
        total_bytes: int = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        total_gibs: int = total_bytes / (1024 * 1024 * 1024)
        required_gibs = BLADEBIT_MIN_RAM_GIBS
        have_enough_memory = total_gibs >= required_gibs
    except Exception as e:
        print(f"Unable to determine total amount of memory: {e}")

    return have_enough_memory


def get_bladebit_install_path(plotters_root_path: Path) -> Path:
    return plotters_root_path / BLADEBIT_PLOTTER_DIR


def get_bladebit_executable_path(plotters_root_path: Path) -> Path:
    return get_bladebit_install_path(plotters_root_path) / ".bin/release/bladebit"


def get_bladebit_install_info(plotters_root_path: Path) -> Optional[Dict[str, Any]]:
    info: Dict[str, Any] = {"display_name": "BladeBit Plotter"}
    installed: bool = False
    supported: bool = is_bladebit_supported()

    if get_bladebit_executable_path(plotters_root_path).exists():
        version: Optional[str] = None
        try:
            proc = subprocess.run(
                [os.fspath(get_bladebit_executable_path(plotters_root_path)), "--version"],
                capture_output=True,
                text=True,
            )
            version = proc.stdout.strip()
        except Exception as e:
            print(f"Failed to determine bladebit version: {e}")

        if version is not None:
            installed = True
            info["version"] = version
        else:
            installed = False

    info["installed"] = installed
    if installed is False:
        info["can_install"] = supported

    if supported and meets_memory_requirement() is False:
        info["bladebit_memory_warning"] = f"BladeBit requires at least {BLADEBIT_MIN_RAM_GIBS} GiB of RAM to operate"

    return info


progress = {
    "Finished F1 sort": 0.01,
    "Finished forward propagating table 2": 0.06,
    "Finished forward propagating table 3": 0.12,
    "Finished forward propagating table 4": 0.2,
    "Finished forward propagating table 5": 0.28,
    "Finished forward propagating table 6": 0.36,
    "Finished forward propagating table 7": 0.42,
    "Finished prunning table 6": 0.43,
    "Finished prunning table 5": 0.48,
    "Finished prunning table 4": 0.51,
    "Finished prunning table 3": 0.55,
    "Finished prunning table 2": 0.58,
    "Finished compressing tables 1 and 2": 0.66,
    "Finished compressing tables 2 and 3": 0.73,
    "Finished compressing tables 3 and 4": 0.79,
    "Finished compressing tables 4 and 5": 0.85,
    "Finished compressing tables 5 and 6": 0.92,
    "Finished compressing tables 6 and 7": 0.98,
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


async def run_bladebit(args):
    cmd = ""
    for arg in args:
        cmd += arg
        cmd += " "
    print(f"Running command: {cmd[:-1]}")
    await run(cmd[:-1])


def install_bladebit(root_path):
    if is_bladebit_supported():
        print("Installing dependencies.")
        try:
            subprocess.run(
                [
                    "sudo",
                    "apt",
                    "install",
                    "-y",
                    "build-essential",
                    "cmake",
                    "libnuma-dev",
                    "git",
                ]
            )
        except Exception:
            raise ValueError("Could not install dependencies.")

        print("Cloning repository and its submodules.")
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--recursive",
                    "https://github.com/harold-b/bladebit.git",
                ],
                cwd=os.fspath(root_path),
            )
        except Exception:
            raise ValueError("Could not clone bladebit repository.")

        bladebit_path = os.fspath(root_path.joinpath("bladebit"))
        print("Building BLS library.")
        # Build bls library. Only needs to be done once.
        try:
            subprocess.run(["./build-bls"], cwd=bladebit_path)
        except Exception as e:
            raise ValueError(f"Building BLS library failed. {e}")

        print("Build bladebit.")
        try:
            subprocess.run(["make", "clean"], cwd=bladebit_path)
            subprocess.run(["make"], cwd=bladebit_path)
        except Exception as e:
            raise ValueError(f"Building bladebit failed. {e}")
    else:
        raise ValueError("Platform not supported yet for bladebit plotter.")


def plot_bladebit(args, root_path):
    if not os.path.exists(root_path / "bladebit/.bin/release/bladebit"):
        print("Installing bladebit plotter.")
        try:
            install_bladebit(root_path)
        except Exception as e:
            print(f"Exception while installing bladebit plotter: {e}")
            return
    call_args = []
    call_args.append(str(root_path) + "/bladebit/.bin/release/bladebit")
    call_args.append("-t")
    call_args.append(str(args.threads))
    call_args.append("-n")
    call_args.append(str(args.count))
    call_args.append("-f")
    call_args.append(args.farmerkey.hex())
    if args.pool_key != b"":
        call_args.append("-p")
        call_args.append(args.pool_key.hex())
    if args.contract != "":
        call_args.append("-c")
        call_args.append(args.contract)
    if args.warmstart:
        call_args.append("-w")
    if args.id != b"":
        call_args.append("-i")
        call_args.append(args.id.hex())
    if args.verbose:
        call_args.append("-v")
    if args.nonuma:
        call_args.append("-m")
    call_args.append(args.finaldir)
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_bladebit(call_args))
    except Exception as e:
        print(f"Exception while plotting: {e} {type(e)}")
        print(f"Traceback: {traceback.format_exc()}")
