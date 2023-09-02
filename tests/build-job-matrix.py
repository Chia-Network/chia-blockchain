from __future__ import annotations

import argparse
import json
import logging
import types
from pathlib import Path
from typing import Any, Dict, List

import testconfig

root_path = Path(__file__).parent.resolve()
project_root_path = root_path.parent


def skip(path: Path) -> bool:
    return any(part.startswith(("_", ".")) for part in path.parts)


def subdirs(per: str) -> List[Path]:
    if per == "directory":
        glob_pattern = "**/"
    elif per == "file":
        glob_pattern = "**/test_*.py"
    else:
        raise Exception(f"Unrecognized per: {per!r}")

    paths = [path for path in root_path.rglob(glob_pattern) if not skip(path=path)]

    if per == "directory":
        filtered_paths = []
        for path in paths:
            relative_path = path.relative_to(root_path)
            logging.info(f"Considering: {relative_path}")
            if len([f for f in path.glob("test_*.py")]) == 0:
                logging.info(f"Skipping {relative_path}: no tests collected")
                continue

            filtered_paths.append(path)

        paths = filtered_paths

    return sorted(paths)


def module_dict(module: types.ModuleType) -> Dict[str, Any]:
    return {k: v for k, v in module.__dict__.items() if not k.startswith("_")}


def dir_config(dir: Path) -> Dict[str, Any]:
    import importlib

    module_name = ".".join([*dir.relative_to(root_path).parts, "config"])
    try:
        return module_dict(importlib.import_module(module_name))
    except ModuleNotFoundError:
        return {}


# Overwrite with directory specific values
def update_config(parent: Dict[str, Any], child: Dict[str, Any]) -> Dict[str, Any]:
    if child is None:
        return parent
    conf = child
    for k, v in parent.items():
        if k not in child:
            conf[k] = v
    return conf


# args
arg_parser = argparse.ArgumentParser(description="Generate GitHub test matrix configuration")
arg_parser.add_argument("--per", type=str, choices=["directory", "file"], required=True)
arg_parser.add_argument("--verbose", "-v", action="store_true")
arg_parser.add_argument("--only", action="append", default=[])
arg_parser.add_argument("--duplicates", type=int, default=1)
arg_parser.add_argument("--timeout-multiplier", type=float, default=1)
args = arg_parser.parse_args()

if args.verbose:
    logging.basicConfig(format="%(asctime)s:%(message)s", level=logging.DEBUG)

# main
if len(args.only) == 0:
    test_paths = subdirs(per=args.per)
else:
    test_paths = [root_path.joinpath(path) for path in args.only]

test_paths = [path for path in test_paths for _ in range(args.duplicates)]

configuration = []

for path in test_paths:
    if path.is_dir():
        test_files = sorted(path.glob("test_*.py"))
        test_file_paths = [file.relative_to(project_root_path) for file in test_files]
        paths_for_cli = " ".join(path.as_posix() for path in test_file_paths)
        conf = update_config(module_dict(testconfig), dir_config(path))
    else:
        paths_for_cli = path.relative_to(project_root_path).as_posix()
        conf = update_config(module_dict(testconfig), dir_config(path.parent))

    # TODO: design a configurable system for this
    process_count = {
        "macos": {False: 0, True: 4}.get(conf["parallel"], conf["parallel"]),
        "ubuntu": {False: 0, True: 4}.get(conf["parallel"], conf["parallel"]),
        "windows": {False: 0, True: 3}.get(conf["parallel"], conf["parallel"]),
    }
    pytest_parallel_args = {os: f" -n {count}" for os, count in process_count.items()}

    for_matrix = {
        "check_resource_usage": conf["check_resource_usage"],
        "enable_pytest_monitor": "-p monitor" if conf["check_resource_usage"] else "",
        "job_timeout": round(conf["job_timeout"] * args.timeout_multiplier),
        "pytest_parallel_args": pytest_parallel_args,
        "checkout_blocks_and_plots": conf["checkout_blocks_and_plots"],
        "install_timelord": conf["install_timelord"],
        "test_files": paths_for_cli,
        "name": ".".join(path.relative_to(root_path).with_suffix("").parts),
        "legacy_keyring_required": conf.get("legacy_keyring_required", False),
    }
    for_matrix = dict(sorted(for_matrix.items()))
    configuration.append(for_matrix)


configuration_json = json.dumps(configuration)

for line in json.dumps(configuration, indent=4).splitlines():
    logging.info(line)

print(f"{configuration_json}")
