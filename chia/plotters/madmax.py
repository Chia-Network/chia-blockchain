import asyncio
import traceback
import os
import logging
import sys

from pathlib import Path
from typing import Any, Dict, Optional
from chia.plotting.create_plots import resolve_plot_keys
from chia.plotters.plotters_util import run_plotter, run_command

log = logging.getLogger(__name__)


MADMAX_PLOTTER_DIR = "madmax-plotter"


def is_madmax_supported() -> bool:
    return sys.platform.startswith("linux") or sys.platform in ["darwin", "win32", "cygwin"]


def get_madmax_install_path(plotters_root_path: Path) -> Path:
    return plotters_root_path / MADMAX_PLOTTER_DIR


def get_madmax_package_path() -> Path:
    return Path(os.path.dirname(sys.executable)) / "madmax"


def get_madmax_executable_path_for_ksize(plotters_root_path: Path, ksize: int = 32) -> Path:
    madmax_dir: Path = get_madmax_package_path()
    madmax_exec: str = "chia_plot"
    if ksize > 32:
        madmax_exec += "_k34"  # Use the chia_plot_k34 executable for k-sizes > 32
    if sys.platform in ["win32", "cygwin"]:
        madmax_exec += ".exe"
    if not madmax_dir.exists():
        madmax_dir = get_madmax_install_path(plotters_root_path) / "build"
    return madmax_dir / madmax_exec


def get_madmax_install_info(plotters_root_path: Path) -> Optional[Dict[str, Any]]:
    info: Dict[str, Any] = {"display_name": "madMAx Plotter"}
    installed: bool = False
    supported: bool = is_madmax_supported()

    if get_madmax_executable_path_for_ksize(plotters_root_path).exists():
        try:
            proc = run_command(
                [os.fspath(get_madmax_executable_path_for_ksize(plotters_root_path)), "--version"],
                "Failed to call madmax with --version option",
                capture_output=True,
                text=True,
            )
            version = proc.stdout.strip()
        except Exception as e:
            print(f"Failed to determine madmax version: {e}")

        if version is not None:
            installed = True
            info["version"] = version
        else:
            installed = False

    info["installed"] = installed
    if installed is False:
        info["can_install"] = supported

    return info


def install_madmax(plotters_root_path: Path):
    if is_madmax_supported():
        print("Installing dependencies.")
        if sys.platform.startswith("linux"):
            run_command(
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
                ],
                "Could not install dependencies",
            )
        if sys.platform.startswith("darwin"):
            run_command(
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
                ],
                "Could not install dependencies",
            )
        run_command(["git", "--version"], "Error checking Git version.")

        print("Cloning git repository.")
        run_command(
            [
                "git",
                "clone",
                "https://github.com/Chia-Network/chia-plotter-madmax.git",
                MADMAX_PLOTTER_DIR,
            ],
            "Could not clone madmax git repository",
            cwd=os.fspath(plotters_root_path),
        )

        print("Installing git submodules.")
        madmax_path: str = os.fspath(get_madmax_install_path(plotters_root_path))
        run_command(
            [
                "git",
                "submodule",
                "update",
                "--init",
                "--recursive",
            ],
            "Could not initialize git submodules",
            cwd=madmax_path,
        )

        print("Running install script.")
        run_command(["./make_devel.sh"], "Error while running install script", cwd=madmax_path)
    else:
        raise RuntimeError("Platform not supported yet for madmax plotter.")


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


def dir_with_trailing_slash(dir: str) -> str:
    return dir if dir[-1] == os.path.sep else dir + os.path.sep


def plot_madmax(args, chia_root_path: Path, plotters_root_path: Path):
    if sys.platform not in ["win32", "cygwin"]:
        import resource

        # madMAx has a ulimit -n requirement > 296:
        # "Cannot open at least 296 files, please raise maximum open file limit in OS."
        resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))

    if not os.path.exists(get_madmax_executable_path_for_ksize(plotters_root_path, args.size)):
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
            args.connect_to_daemon,
        )
    )
    call_args = []
    call_args.append(os.fspath(get_madmax_executable_path_for_ksize(plotters_root_path, args.size)))
    call_args.append("-f")
    call_args.append(bytes(plot_keys.farmer_public_key).hex())
    if plot_keys.pool_public_key is not None:
        call_args.append("-p")
        call_args.append(bytes(plot_keys.pool_public_key).hex())
    call_args.append("-t")
    # s if s[-1] == os.path.sep else s + os.path.sep
    call_args.append(dir_with_trailing_slash(args.tmpdir))
    call_args.append("-2")
    call_args.append(dir_with_trailing_slash(args.tmpdir2))
    call_args.append("-d")
    call_args.append(dir_with_trailing_slash(args.finaldir))
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
        loop.run_until_complete(run_plotter(call_args, progress))
    except Exception as e:
        print(f"Exception while plotting: {type(e)} {e}")
        print(f"Traceback: {traceback.format_exc()}")
