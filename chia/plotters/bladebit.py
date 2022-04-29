import asyncio
import json
import traceback
import os
import sys
import logging

from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from chia.plotting.create_plots import resolve_plot_keys
from chia.plotters.plotters_util import run_plotter, run_command, check_git_repository, check_git_ref

log = logging.getLogger(__name__)


BLADEBIT_PLOTTER_DIR = "bladebit"


def is_bladebit_supported() -> bool:
    # bladebit >= 2.0.0 now supports macOS
    return sys.platform.startswith("linux") or sys.platform in ["win32", "cygwin", "darwin"]


def meets_memory_requirement(plotters_root_path: Path) -> Tuple[bool, Optional[str]]:
    have_enough_memory: bool = False
    warning_string: Optional[str] = None

    bladebit_executable_path = get_bladebit_executable_path(plotters_root_path)
    if bladebit_executable_path.exists():
        try:
            proc = run_command(
                [os.fspath(bladebit_executable_path), "--memory-json"],
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


def get_bladebit_exec_install_path(plotters_root_path: Path) -> Path:
    bladebit_install_dir = get_bladebit_install_path(plotters_root_path)
    build_dir = "build/Release" if sys.platform in ["win32", "cygwin"] else "build"
    bladebit_exec = "bladebit.exe" if sys.platform in ["win32", "cygwin"] else "bladebit"
    return bladebit_install_dir / build_dir / bladebit_exec


def get_bladebit_exec_package_path() -> Path:
    bladebit_package_dir = get_bladebit_package_path()
    bladebit_exec = "bladebit.exe" if sys.platform in ["win32", "cygwin"] else "bladebit"
    return bladebit_package_dir / bladebit_exec


def get_bladebit_executable_path(plotters_root_path: Path) -> Path:
    bladebit_exec_path = get_bladebit_exec_install_path(plotters_root_path)
    if bladebit_exec_path.exists():
        return bladebit_exec_path
    return get_bladebit_exec_package_path()


def get_bladebit_version(plotters_root_path: Path):
    bladebit_executable_path = get_bladebit_executable_path(plotters_root_path)
    if bladebit_executable_path.exists():
        try:
            proc = run_command(
                [os.fspath(bladebit_executable_path), "--version"],
                "Failed to call bladebit with --version option",
                capture_output=True,
                text=True,
            )
            # (Found, versionStr)
            version_str: str = proc.stdout.strip()
            return True, version_str.split(".")
        except Exception as e:
            # (Unknown, Exception)
            return None, e
    else:
        # (NotFound, "")
        return False, ""


def get_bladebit_install_info(plotters_root_path: Path) -> Optional[Dict[str, Any]]:
    info: Dict[str, Any] = {"display_name": "BladeBit Plotter"}
    installed: bool = False
    supported: bool = is_bladebit_supported()

    bladebit_executable_path = get_bladebit_executable_path(plotters_root_path)
    if bladebit_executable_path.exists():
        version: Optional[str] = None
        found, response = get_bladebit_version(plotters_root_path)
        if found:
            version = ".".join(response)
        elif found is None:
            print(f"Failed to determine bladebit version: {response}")

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


def install_bladebit(root_path: Path, override: bool = False, commit: Optional[str] = None):
    if not override and os.path.exists(get_bladebit_executable_path(root_path)):
        print("Bladebit plotter already installed.")
        print("You can override it with -o option")
        return

    if not is_bladebit_supported():
        raise RuntimeError("Platform not supported yet for bladebit plotter.")

    if commit and not check_git_ref(commit):
        raise RuntimeError("commit contains unusual string. Aborted.")

    print("Installing bladebit plotter.")

    if sys.platform in ["win32", "cygwin"]:
        print("Windows user must build bladebit manually on <chia_root>\\plotters\\bladebit")
        print("Please run `git clone` on the folder then build it as instructed in README")
        raise RuntimeError("Automatic install not supported on Windows")

    if sys.platform.startswith("linux"):
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
                "libgmp-dev",
            ],
            "Could not install dependencies",
        )
    elif sys.platform in ["darwin"]:
        # 'brew' is a requirement for chia on macOS, so it should be available.
        run_command(["brew", "install", "cmake"], "Could not install dependencies")

    bladebit_path: str = os.fspath(root_path.joinpath("bladebit"))
    bladebit_git_origin_url = "https://github.com/Chia-Network/bladebit.git"
    bladebit_git_repos_exist = check_git_repository(bladebit_path, bladebit_git_origin_url)

    if bladebit_git_repos_exist:
        if commit:
            run_command(["git", "fetch", "origin"], "Failed to fetch origin", cwd=bladebit_path)
            run_command(["git", "checkout", "-f", commit], f"Failed to reset to {commit}", cwd=bladebit_path)
        elif override:
            run_command(["git", "fetch", "origin"], "Failed to fetch origin", cwd=bladebit_path)
            run_command(
                ["git", "reset", "--hard", "origin/master"], "Failed to reset to origin/master", cwd=bladebit_path
            )
        else:
            # Rebuild with existing files
            pass
    else:
        if commit:
            run_command(
                ["git", "clone", "--recursive", "--branch", commit, bladebit_git_origin_url],
                "Could not clone bladebit repository",
                cwd=os.fspath(root_path),
            )
        else:
            print("Cloning repository and its submodules.")
            run_command(
                ["git", "clone", "--recursive", bladebit_git_origin_url],
                "Could not clone bladebit repository",
                cwd=os.fspath(root_path),
            )

    build_path: str = os.fspath(Path(bladebit_path) / "build")

    print("Build bladebit.")
    if not os.path.exists(bladebit_path):
        run_command(["mkdir", build_path], "Failed to create build directory", cwd=bladebit_path)
    run_command(["cmake", ".."], "Failed to generate build config", cwd=build_path)
    run_command(
        ["cmake", "--build", ".", "--target", "bladebit", "--config", "Release"],
        "Building bladebit failed",
        cwd=build_path,
    )


def plot_bladebit(args, chia_root_path, root_path):
    (found, version_or_exception) = get_bladebit_version(root_path)
    if found is None:
        print(f"Error: {version_or_exception}")
        return

    version = None
    if args.plotter == "bladebit":
        version = 1
        if found and version_or_exception[0] != "1":
            print(
                f"You're trying to run bladebit version 1"
                f" but currently version {'.'.join(version_or_exception)} is installed"
            )
            return
    elif args.plotter == "bladebit2":
        version = 2
        if found and version_or_exception[0] != "2":
            print(
                f"You're trying to run bladebit version 2"
                f" but currently version {'.'.join(version_or_exception)} is installed"
            )
            return

    if version is None:
        print(f"Unknown version of bladebit: {args.plotter}")
        return

    # When neither bladebit installed from git nor bladebit bundled with installer is available,
    # install bladebit from git repos.
    if not os.path.exists(get_bladebit_executable_path(root_path)):
        print("Installing bladebit plotter.")
        try:
            # TODO: Change commit hash/branch name appropriately
            if version == 1:
                commit = "ad85a8f2cf99ca4c757932a21d937fdc9c7ae0ef"
            elif version == 2:
                commit = "disk-plot"
            else:
                print(f"Unknown bladebit version {version}")
                return

            install_bladebit(root_path, True, commit)
        except Exception as e:
            print(f"Exception while installing bladebit plotter: {e}")
            return

    plot_keys = asyncio.run(
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
    call_args = [
        os.fspath(get_bladebit_executable_path(root_path)),
        "-t",
        str(args.threads),
        "-n",
        str(args.count),
        "-f",
        bytes(plot_keys.farmer_public_key).hex(),
    ]
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
    if args.memo is not None and args.memo != b"":
        call_args.append("--memo")
        call_args.append(args.memo)
    if version > 1:
        call_args.append("diskplot")
    if args.buckets:
        call_args.append("-b")
        call_args.append(str(args.buckets))
    if args.tmpdir:
        call_args.append("-t1")
        call_args.append(str(args.tmpdir))
    if args.tmpdir2:
        call_args.append("-t2")
        call_args.append(str(args.tmpdir2))
    if args.no_cpu_affinity:
        call_args.append("--no-cpu-affinity")
    if args.cache is not None:
        call_args.append("--cache")
        call_args.append(str(args.cache))
    if args.f1_threads:
        call_args.append("--f1-threads")
        call_args.append(str(args.f1_threads))
    if args.fp_threads:
        call_args.append("--fp-threads")
        call_args.append(str(args.fp_threads))
    if args.c_threads:
        call_args.append("--c-threads")
        call_args.append(str(args.c_threads))
    if args.p2_threads:
        call_args.append("--p2-threads")
        call_args.append(str(args.p2_threads))
    if args.p3_threads:
        call_args.append("--p3-threads")
        call_args.append(str(args.p3_threads))

    call_args.append(args.finaldir)

    try:
        asyncio.run(run_plotter(call_args, progress))
    except Exception as e:
        print(f"Exception while plotting: {e} {type(e)}")
        print(f"Traceback: {traceback.format_exc()}")
