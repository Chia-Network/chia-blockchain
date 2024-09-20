from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from chia.plotters.plotters_util import get_venv_bin, reset_loop_policy_for_windows, run_command, run_plotter
from chia.plotting.create_plots import resolve_plot_keys

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
                check=False,
            )
            if proc.returncode != 0:
                return have_enough_memory, proc.stderr.strip()

            memory_info: Dict[str, int] = json.loads(proc.stdout)
            total_bytes: int = memory_info.get("total", -1)
            required_bytes: int = memory_info.get("required", 0)
            have_enough_memory = total_bytes >= required_bytes
            if have_enough_memory is False:
                warning_string = f"BladeBit requires at least {int(required_bytes / 1024**3)} GiB of RAM to operate"
        except Exception as e:
            print(f"Failed to determine bladebit memory requirements: {e}")

    return have_enough_memory, warning_string


def is_cudaplot_available(plotters_root_path: Path) -> bool:
    bladebit_executable_path = get_bladebit_executable_path(plotters_root_path)
    if not bladebit_executable_path.exists():
        return False
    try:
        proc = run_command(
            [os.fspath(bladebit_executable_path), "cudacheck"],
            "Failed to call bladebit with cudacheck command",
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode == 0
    except Exception as e:
        print(f"Failed to determine whether bladebit supports cuda: {e}")
        return False


def get_bladebit_src_path(plotters_root_path: Path) -> Path:
    return plotters_root_path / BLADEBIT_PLOTTER_DIR


def get_bladebit_package_path() -> Path:
    p = Path(os.path.dirname(sys.executable)).joinpath("_internal/bladebit")
    if p.exists():
        return p
    return Path(os.path.dirname(sys.executable)).joinpath("bladebit")


def get_bladebit_exec_path(with_cuda: bool = False) -> str:
    if with_cuda:
        return "bladebit_cuda.exe" if sys.platform in ["win32", "cygwin"] else "bladebit_cuda"
    return "bladebit.exe" if sys.platform in ["win32", "cygwin"] else "bladebit"


def get_bladebit_exec_venv_path(with_cuda: bool = False) -> Optional[Path]:
    venv_bin_path = get_venv_bin()
    if not venv_bin_path:
        return None
    bladebit_exec = get_bladebit_exec_path(with_cuda)
    return venv_bin_path / bladebit_exec


def get_bladebit_exec_src_path(plotters_root_path: Path, with_cuda: bool = False) -> Path:
    bladebit_src_dir = get_bladebit_src_path(plotters_root_path)
    build_dir = "build/Release" if sys.platform in ["win32", "cygwin"] else "build"
    bladebit_exec = get_bladebit_exec_path(with_cuda)
    return bladebit_src_dir / build_dir / bladebit_exec


def get_bladebit_exec_package_path(with_cuda: bool = False) -> Path:
    bladebit_package_dir = get_bladebit_package_path()
    bladebit_exec = get_bladebit_exec_path(with_cuda)
    return bladebit_package_dir / bladebit_exec


def get_bladebit_executable_path(plotters_root_path: Path) -> Path:
    # Search for bladebit executable which supports CUDA at the first priority
    bladebit_exec_venv_path = get_bladebit_exec_venv_path(with_cuda=True)
    if bladebit_exec_venv_path is not None and bladebit_exec_venv_path.exists():
        return bladebit_exec_venv_path
    bladebit_exec_src_path = get_bladebit_exec_src_path(plotters_root_path, with_cuda=True)
    if bladebit_exec_src_path.exists():
        return bladebit_exec_src_path
    bladebit_exec_package_path = get_bladebit_exec_package_path(with_cuda=True)
    if bladebit_exec_package_path.exists():
        return bladebit_exec_package_path

    bladebit_exec_venv_path = get_bladebit_exec_venv_path(with_cuda=False)
    if bladebit_exec_venv_path is not None and bladebit_exec_venv_path.exists():
        return bladebit_exec_venv_path
    bladebit_exec_src_path = get_bladebit_exec_src_path(plotters_root_path, with_cuda=False)
    if bladebit_exec_src_path.exists():
        return bladebit_exec_src_path
    return get_bladebit_exec_package_path(with_cuda=False)


def get_bladebit_version(
    plotters_root_path: Path,
) -> Union[Tuple[Literal[False], str], Tuple[None, str], Tuple[Literal[True], List[str]]]:
    bladebit_executable_path = get_bladebit_executable_path(plotters_root_path)
    if not bladebit_executable_path.exists():
        # (found=False, "")
        return False, ""

    try:
        proc = run_command(
            [os.fspath(bladebit_executable_path), "--version"],
            "Failed to call bladebit with --version option",
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            # (found=unknown, errMsg)
            return None, proc.stderr.strip()

        # (found=True, versionStr)
        version_str: str = proc.stdout.strip()
        return True, version_str.split(".")
    except Exception as e:
        # (found=unknown, errMsg)
        return None, str(e)


def get_bladebit_install_info(plotters_root_path: Path) -> Optional[Dict[str, Any]]:
    info: Dict[str, Any] = {"display_name": "BladeBit Plotter"}
    installed: bool = False
    supported: bool = is_bladebit_supported()
    cuda_available: bool = is_cudaplot_available(plotters_root_path)

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

    info["cuda_support"] = cuda_available

    return info


progress_bladebit_cuda = {
    "Generating F1": 0.01,
    "Finished F1 in ": 0.1,
    "Table 2 completed in ": 0.2,
    "Table 3 completed in ": 0.3,
    "Table 4 completed in ": 0.4,
    "Table 5 completed in ": 0.5,
    "Table 6 completed in ": 0.6,
    "Table 7 completed in ": 0.7,
    "Completed Phase 1 in ": 0.8,
    "Completed Phase 2 in ": 0.9,
    "Completed Phase 3 in ": 0.95,
}

progress_bladebit_ram = {
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

progress_bladebit_disk = {
    # "Running Phase 1": 0.01,
    "Finished f1 generation in ": 0.01,
    "Completed table 2 in ": 0.06,
    "Completed table 3 in ": 0.12,
    "Completed table 4 in ": 0.2,
    "Completed table 5 in ": 0.28,
    "Completed table 6 in ": 0.36,
    "Completed table 7 in ": 0.42,
    # "Finished Phase 1 ": 0.43,
    # "Running Phase 2": 0.43,
    "Finished marking table 6 in ": 0.43,
    "Finished marking table 5 in ": 0.48,
    "Finished marking table 4 in ": 0.51,
    "Finished marking table 3 in ": 0.55,
    "Finished marking table 2 in ": 0.58,
    # "Finished Phase 2 ": 0.59,
    # "Running Phase 3": 0.60,
    "Finished compressing tables 1 and 2 in ": 0.66,
    "Finished compressing tables 2 and 3 in ": 0.73,
    "Finished compressing tables 3 and 4 in ": 0.79,
    "Finished compressing tables 4 and 5 in ": 0.85,
    "Finished compressing tables 5 and 6 in ": 0.92,
    "Finished compressing tables 6 and 7 in ": 0.98,
    # "Finished Phase 3 ": 0.99,
    "Finished writing plot ": 0.99,
}


def plot_bladebit(args, chia_root_path, root_path):
    (found, version_or_exception) = get_bladebit_version(root_path)
    if found is None:
        print(f"Error: {version_or_exception}")
        return

    if found and int(version_or_exception[0]) < 2:
        print(f"Version {'.'.join(version_or_exception)} is detected.")
        print("bladebit < 2 is not supported any more.")
        return

    bladebit_executable_path = get_bladebit_executable_path(root_path)
    if not os.path.exists(bladebit_executable_path):
        print("Bladebit was not found.")
        return

    if sys.platform in ["win32", "cygwin"]:
        reset_loop_policy_for_windows()

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
    if args.plot_type == "ramplot" or args.plot_type == "diskplot" or args.plot_type == "cudaplot":
        plot_type = args.plot_type
    else:
        plot_type = "diskplot"
        print("plot_type is automatically set to diskplot")

    call_args = [
        os.fspath(bladebit_executable_path),
        "--threads",
        str(args.threads),
        "--count",
        str(args.count),
        "--farmer-key",
        bytes(plot_keys.farmer_public_key).hex(),
    ]
    if plot_keys.pool_public_key is not None:
        call_args.append("--pool-key")
        call_args.append(bytes(plot_keys.pool_public_key).hex())
    if plot_keys.pool_contract_address is not None:
        call_args.append("--pool-contract")
        call_args.append(plot_keys.pool_contract_address)
    if args.warmstart:
        call_args.append("--warm-start")
    if args.id is not None and args.id != b"":
        call_args.append("--plot-id")
        call_args.append(args.id.hex())
    if "memo" in args and args.memo is not None and args.memo != b"":
        call_args.append("--memo")
        call_args.append(args.memo)
    if args.nonuma:
        call_args.append("--no-numa")
    if args.no_cpu_affinity:
        call_args.append("--no-cpu-affinity")
    if args.verbose:
        call_args.append("--verbose")
    if (
        "compress" in args
        and args.compress is not None
        and str(args.compress).isdigit()
        and int(version_or_exception[0]) >= 3
    ):
        call_args.append("--compress")
        call_args.append(str(args.compress))

    call_args.append(plot_type)

    if "buckets" in args and args.buckets:
        call_args.append("--buckets")
        call_args.append(str(args.buckets))
    if "tmpdir" in args and args.tmpdir:
        call_args.append("--temp1")
        call_args.append(str(args.tmpdir))
    if "tmpdir2" in args and args.tmpdir2:
        call_args.append("--temp2")
        call_args.append(str(args.tmpdir2))
    if "cache" in args and args.cache is not None:
        call_args.append("--cache")
        call_args.append(str(args.cache))
    if "f1_threads" in args and args.f1_threads:
        call_args.append("--f1-threads")
        call_args.append(str(args.f1_threads))
    if "fp_threads" in args and args.fp_threads:
        call_args.append("--fp-threads")
        call_args.append(str(args.fp_threads))
    if "c_threads" in args and args.c_threads:
        call_args.append("--c-threads")
        call_args.append(str(args.c_threads))
    if "p2_threads" in args and args.p2_threads:
        call_args.append("--p2-threads")
        call_args.append(str(args.p2_threads))
    if "p3_threads" in args and args.p3_threads:
        call_args.append("--p3-threads")
        call_args.append(str(args.p3_threads))
    if "alternate" in args and args.alternate:
        call_args.append("--alternate")
    if "no_t1_direct" in args and args.no_t1_direct:
        call_args.append("--no-t1-direct")
    if "no_t2_direct" in args and args.no_t2_direct:
        call_args.append("--no-t2-direct")
    if "device" in args and str(args.device).isdigit():
        call_args.append("--device")
        call_args.append(str(args.device))
    if "disk_128" in args and args.disk_128:
        call_args.append("--disk-128")
    if "disk_16" in args and args.disk_16:
        call_args.append("--disk-16")

    call_args.append(args.finaldir)

    try:
        if plot_type == "cudaplot":
            progress = progress_bladebit_cuda
        elif plot_type == "ramplot":
            progress = progress_bladebit_ram
        else:
            progress = progress_bladebit_disk
        asyncio.run(run_plotter(chia_root_path, args.plotter, call_args, progress))
    except Exception as e:
        print(f"Exception while plotting: {e} {type(e)}")
        print(f"Traceback: {traceback.format_exc()}")
