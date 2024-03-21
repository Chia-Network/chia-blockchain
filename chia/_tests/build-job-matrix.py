from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import types
from pathlib import Path
from typing import Any, Dict, List

import testconfig

root_path = Path(__file__).parent.absolute()
project_root_path = root_path.parent.parent


def skip(path: Path) -> bool:
    return any(part.startswith(("_", ".")) and part != "_tests" for part in path.parts)


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
    return {k: v for k, v in module.__dict__.items() if not k.startswith("_") and k != "annotations"}


def dir_config(dir: Path) -> Dict[str, Any]:
    import importlib

    module_name = ".".join([*dir.relative_to(root_path).parts, "config"])
    try:
        return module_dict(importlib.import_module(module_name))
    except ModuleNotFoundError:
        return {}


@dataclasses.dataclass
class SpecifiedDefaultsError(Exception):
    overlap: Dict[str, Any]

    def __post_init__(self) -> None:
        super().__init__()


# Overwrite with directory specific values
def update_config(parent: Dict[str, Any], child: Dict[str, Any]) -> Dict[str, Any]:
    if child is None:
        return parent
    conf = child

    # avoid manual configuration set to default values
    common_keys = set(parent.keys()).intersection(child.keys())
    specified_defaulted_values = {k: parent[k] for k in common_keys if parent[k] == child[k]}
    if len(specified_defaulted_values) > 0:
        raise SpecifiedDefaultsError(overlap=specified_defaulted_values)

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

test_paths_with_index = [(path, index + 1) for path in test_paths for index in range(args.duplicates)]

configuration = []

specified_defaults: Dict[Path, Dict[str, Any]] = {}
pytest_monitor_enabling_paths: List[Path] = []

for path, index in test_paths_with_index:
    if path.is_dir():
        test_files = sorted(path.glob("test_*.py"))
        paths_for_cli_list = [file.relative_to(project_root_path) for file in test_files]
        config_path = path
    else:
        paths_for_cli_list = [path.relative_to(project_root_path)]
        config_path = path.parent

    def mung_path(path: Path) -> str:
        # TODO: shell escaping, but that's per platform...
        return ".".join(path.with_suffix("").parts)

    paths_for_cli = " ".join(mung_path(path) for path in paths_for_cli_list)
    paths_for_cli = f"--pyargs {paths_for_cli}"

    try:
        conf = update_config(module_dict(testconfig), dir_config(config_path))
    except SpecifiedDefaultsError as e:
        specified_defaults[root_path.joinpath(config_path, "config.py")] = e.overlap
        continue

    # TODO: design a configurable system for this
    process_count = {
        "macos": {False: 0, True: 4}.get(conf["parallel"], conf["parallel"]),
        "ubuntu": {False: 0, True: 6}.get(conf["parallel"], conf["parallel"]),
        "windows": {False: 0, True: 4}.get(conf["parallel"], conf["parallel"]),
    }
    pytest_parallel_args = {os: f" -n {count}" for os, count in process_count.items()}

    enable_pytest_monitor = conf["check_resource_usage"]

    if enable_pytest_monitor:
        # NOTE: do not use until the hangs are fixed
        #       https://github.com/CFMTech/pytest-monitor/issues/53
        #       https://github.com/pythonprofilers/memory_profiler/issues/342

        pytest_monitor_enabling_paths.append(path)

    max_index_characters = len(str(args.duplicates))
    index_string = f"{index:0{max_index_characters}d}"
    module_import_path = ".".join(path.relative_to(root_path).with_suffix("").parts)
    if args.duplicates == 1:
        name = module_import_path
        file_name_index = ""
    else:
        name = f"{module_import_path} #{index_string}"
        file_name_index = f"_{index_string}"

    for_matrix = {
        "check_resource_usage": conf["check_resource_usage"],
        "enable_pytest_monitor": "-p monitor" if enable_pytest_monitor else "",
        "job_timeout": round(conf["job_timeout"] * args.timeout_multiplier),
        "pytest_parallel_args": pytest_parallel_args,
        "checkout_blocks_and_plots": conf["checkout_blocks_and_plots"],
        "install_timelord": conf["install_timelord"],
        "test_files": paths_for_cli,
        "name": name,
        "legacy_keyring_required": conf.get("legacy_keyring_required", False),
        "index": index,
        "index_string": index_string,
        "module_import_path": module_import_path,
        "file_name_index": file_name_index,
    }
    for_matrix = dict(sorted(for_matrix.items()))
    configuration.append(for_matrix)

messages: List[str] = []

if len(specified_defaults) > 0:
    message = f"Found {len(specified_defaults)} directories with specified defaults"
    messages.append(message)
    logging.error(f"{message}:")
    for path, overlap in sorted(specified_defaults.items()):
        logging.error(f" {path} : {overlap}")

if len(pytest_monitor_enabling_paths) > 0:
    message = f"Found {len(pytest_monitor_enabling_paths)} directories with pytest-monitor enabled"
    messages.append(message)
    logging.error(f"{message}:")
    for path in sorted(pytest_monitor_enabling_paths):
        logging.error(f" {path}")

if len(messages) > 0:
    raise Exception("\n".join(messages))

configuration_json = json.dumps(configuration)

for line in json.dumps(configuration, indent=2).splitlines():
    logging.info(line)

print(f"{configuration_json}")
