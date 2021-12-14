import asyncio
import json
import traceback
import os
import sys
import logging

from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from chia.plotting.create_plots import resolve_plot_keys
from chia.plotters.plotters_util import run_plotter, run_command

log = logging.getLogger(__name__)


BLADEBIT_PLOTTER_DIR = "bladebit"


def is_bladebit_supported() -> bool:
    return sys.platform.startswith("linux") or sys.platform in ["win32", "cygwin"]


def meets_memory_requirement(plotters_root_path: Path) -> Tuple[bool, Optional[str]]:
    have_enough_memory: bool = False
    warning_string: Optional[str] = None
    if get_bladebit_executable_path(plotters_root_path).exists():
        try:
            proc = run_command(
                [os.fspath(get_bladebit_executable_path(plotters_root_path)), "--memory-json"],
                "Failed to call bladebit with --memory-json option",
                capture_output=True,
                text=True,
            )
            memory_info: Dict[str, int] = json.loads(proc.stdout)
            total_bytes: int = memory_info.get("total", -1)
            required_bytes: int = memory_info.get("required", 0)
            have_enough_memory = total_bytes >= required_bytes
            if have_enough_memory is False:
                warning_string = f"BladeBit requires at least {int(required_bytes / 1024**3)} GiB of RAM to operate"
        except Exception as e:
            print(f"Failed to determine bladebit memory requirements: {e}")

    return have_enough_memory, warning_string


def get_bladebit_install_path(plotters_root_path: Path) -> Path:
    return plotters_root_path / BLADEBIT_PLOTTER_DIR


def get_bladebit_package_path() -> Path:
    return Path(os.path.dirname(sys.executable)) / "bladebit"


def get_bladebit_executable_path(plotters_root_path: Path) -> Path:
    bladebit_dir: Path = get_bladebit_package_path()
    bladebit_exec: str = "bladebit"
    build_dir: str = "build"
    if sys.platform in ["win32", "cygwin"]:
        bladebit_exec = "bladebit.exe"
        build_dir = "build/Release"
    if not bladebit_dir.exists():
        bladebit_dir = get_bladebit_install_path(plotters_root_path) / build_dir
    return bladebit_dir / bladebit_exec


def get_bladebit_install_info(plotters_root_path: Path) -> Optional[Dict[str, Any]]:
    info: Dict[str, Any] = {"display_name": "BladeBit Plotter"}
    installed: bool = False
    supported: bool = is_bladebit_supported()

    if get_bladebit_executable_path(plotters_root_path).exists():
        version: Optional[str] = None
        try:
            proc = run_command(
                [os.fspath(get_bladebit_executable_path(plotters_root_path)), "--version"],
                "Failed to call bladebit with --version option",
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

    if supported:
        _, memory_warning = meets_memory_requirement(plotters_root_path)
        if memory_warning is not None:
            info["bladebit_memory_warning"] = memory_warning

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


def install_bladebit(root_path):
    if is_bladebit_supported():
        print("Installing dependencies.")
        run_command(
            [
                "sudo",
                "apt",
                "install",
                "-y",
                "build-essential",
                "cmake",
                "libnuma-dev",
                "git",
            ],
            "Could not install dependencies",
        )

        print("Cloning repository and its submodules.")
        run_command(
            [
                "git",
                "clone",
                "--recursive",
                "https://github.com/Chia-Network/bladebit.git",
            ],
            "Could not clone bladebit repository",
            cwd=os.fspath(root_path),
        )

        bladebit_path: str = os.fspath(root_path.joinpath("bladebit"))
        build_path: str = os.fspath(Path(bladebit_path) / "build")

        print("Build bladebit.")
        run_command(["mkdir", build_path], "Failed to create build directory", cwd=bladebit_path)
        run_command(["cmake", ".."], "Failed to generate build config", cwd=build_path)
        run_command(
            ["cmake", "--build", ".", "--target", "bladebit", "--config", "Release"],
            "Building bladebit failed",
            cwd=build_path,
        )
    else:
        raise RuntimeError("Platform not supported yet for bladebit plotter.")


def plot_bladebit(args, chia_root_path, root_path):
    if not os.path.exists(get_bladebit_executable_path(root_path)):
        print("Installing bladebit plotter.")
        try:
            install_bladebit(root_path)
        except Exception as e:
            print(f"Exception while installing bladebit plotter: {e}")
            return
    plot_keys = asyncio.get_event_loop().run_until_complete(
        resolve_plot_keys(
            None if args.farmerkey == b"" else args.farmerkey.hex(),
            None,
            None if args.pool_key == b"" else args.pool_key.hex(),
            None if args.contract == "" else args.contract,
            chia_root_path,
            log,
            args.connect_to_daemon,
        )
    )
    call_args = []
    call_args.append(os.fspath(get_bladebit_executable_path(root_path)))
    call_args.append("-t")
    call_args.append(str(args.threads))
    call_args.append("-n")
    call_args.append(str(args.count))
    call_args.append("-f")
    call_args.append(bytes(plot_keys.farmer_public_key).hex())
    if plot_keys.pool_public_key is not None:
        call_args.append("-p")
        call_args.append(bytes(plot_keys.pool_public_key).hex())
    if plot_keys.pool_contract_address is not None:
        call_args.append("-c")
        call_args.append(plot_keys.pool_contract_address)
    if args.warmstart:
        call_args.append("-w")
    if args.id is not None and args.id != b"":
        call_args.append("-i")
        call_args.append(args.id.hex())
    if args.verbose:
        call_args.append("-v")
    if args.nonuma:
        call_args.append("-m")
    call_args.append(args.finaldir)
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_plotter(call_args, progress))
    except Exception as e:
        print(f"Exception while plotting: {e} {type(e)}")
        print(f"Traceback: {traceback.format_exc()}")
