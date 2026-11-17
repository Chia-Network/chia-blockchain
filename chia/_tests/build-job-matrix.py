from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import types
from pathlib import Path
from typing import Any

import matrix_shard  # type: ignore[import-not-found]
import testconfig

log = logging.getLogger(__name__)

root_path = Path(__file__).parent.absolute()
project_root_path = root_path.parent.parent

# Not per-directory settings. Kept on testconfig so the matrix script is the
# only place that decides which directories share a row.
_NON_DIRECTORY_KEYS = {"matrix_packs"}


def skip(path: Path) -> bool:
    return any(part.startswith(("_", ".")) and part != "_tests" for part in path.relative_to(root_path).parts)


def subdirs(per: str) -> list[Path]:
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
            log.info(f"Considering: {relative_path}")
            if len([f for f in path.glob("test_*.py")]) == 0:
                log.info(f"Skipping {relative_path}: no tests collected")
                continue

            filtered_paths.append(path)

        paths = filtered_paths

    return sorted(paths)


def module_dict(module: types.ModuleType) -> dict[str, Any]:
    return {k: v for k, v in module.__dict__.items() if not k.startswith("_") and k != "annotations"}


def directory_defaults() -> dict[str, Any]:
    return {key: value for key, value in module_dict(testconfig).items() if key not in _NON_DIRECTORY_KEYS}


def dir_config(dir: Path) -> dict[str, Any]:
    import importlib

    module_name = ".".join([*dir.relative_to(root_path).parts, "config"])
    try:
        return module_dict(importlib.import_module(module_name))
    except ModuleNotFoundError:
        return {}


@dataclasses.dataclass
class SpecifiedDefaultsError(Exception):
    overlap: dict[str, Any]

    def __post_init__(self) -> None:
        super().__init__()


# Overwrite with directory specific values
def update_config(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
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


def test_file_ref(path: Path) -> matrix_shard.TestFile:
    relative = path.relative_to(project_root_path)
    return matrix_shard.TestFile(
        filename=path.name,
        module=".".join(relative.with_suffix("").parts),
        repo_path=relative.as_posix(),
    )


def tests_import_path(path: Path) -> str:
    """Job name path relative to ``chia/_tests`` (no ``chia._tests`` prefix, no suffix)."""
    return ".".join(path.relative_to(root_path).with_suffix("").parts)


def parallel_args(parallel: Any) -> dict[str, str]:
    # bool uses the historical per-OS default. An int is an explicit worker count.
    process_count = {
        "macos": {False: 0, True: 4}.get(parallel, parallel),
        "ubuntu": {False: 0, True: 6}.get(parallel, parallel),
        "windows": {False: 0, True: 4}.get(parallel, parallel),
    }
    return {os: f" -n {count}" for os, count in process_count.items()}


def merged_pack_config(members: list[dict[str, Any]]) -> dict[str, Any]:
    """One row's settings. Parallelism and timelord must already match.

    Timeout is the max so a packed row is never killed sooner than its
    longest member. Block/plot checkout is on if any member needs it.
    """
    merged = dict(members[0])
    merged["job_timeout"] = max(member["job_timeout"] for member in members)
    merged["checkout_blocks_and_plots"] = any(member["checkout_blocks_and_plots"] for member in members)
    return merged


def row_for(
    *,
    conf: dict[str, Any],
    pieces: list[matrix_shard.Piece],
    name: str,
    module_import_path: str,
    file_name_index: str,
    index: int,
    index_string: str,
    timeout_multiplier: float,
) -> dict[str, Any]:
    enable_pytest_monitor = conf["check_resource_usage"]
    for_matrix = {
        "check_resource_usage": conf["check_resource_usage"],
        "enable_pytest_monitor": "-p monitor" if enable_pytest_monitor else "",
        "job_timeout": round(conf["job_timeout"] * timeout_multiplier),
        "pytest_parallel_args": parallel_args(conf["parallel"]),
        "checkout_blocks_and_plots": conf["checkout_blocks_and_plots"],
        "install_timelord": conf["install_timelord"],
        "test_files": matrix_shard.render_test_files(pieces),
        "name": name,
        "index": index,
        "index_string": index_string,
        "module_import_path": module_import_path,
        "file_name_index": file_name_index,
    }
    return dict(sorted(for_matrix.items()))


@dataclasses.dataclass
class DirectoryPlan:
    path: Path
    relative: str
    files: list[Path]
    conf: dict[str, Any]


def compatible_pack(members: list[DirectoryPlan]) -> None:
    first = members[0].conf
    for member in members[1:]:
        if member.conf["parallel"] != first["parallel"] or member.conf["install_timelord"] != first["install_timelord"]:
            msg = "refusing to pack directories with different parallel or install_timelord settings: " + ", ".join(
                member.relative for member in members
            )
            raise Exception(msg)
        if member.conf["check_resource_usage"] != first["check_resource_usage"]:
            msg = "refusing to pack directories with different check_resource_usage settings: " + ", ".join(
                member.relative for member in members
            )
            raise Exception(msg)
        if int(member.conf["matrix_shards"]) != 1 or int(first["matrix_shards"]) != 1:
            msg = "refusing to pack a directory that also sets matrix_shards: " + ", ".join(
                member.relative for member in members
            )
            raise Exception(msg)


def shard_rows(
    *,
    module_import_path: str,
    pieces_by_shard: list[list[matrix_shard.Piece]],
    conf: dict[str, Any],
    duplicates: int,
    timeout_multiplier: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    shard_count = len(pieces_by_shard)
    width = len(str(duplicates))
    for shard_number, pieces in enumerate(pieces_by_shard, start=1):
        shard_name = module_import_path if shard_count == 1 else f"{module_import_path} {shard_number}/{shard_count}"
        shard_suffix = "" if shard_count == 1 else f"_{shard_number}of{shard_count}"
        for index in range(duplicates):
            number = index + 1
            index_string = f"{number:0{width}d}"
            if duplicates == 1:
                name = shard_name
                file_name_index = shard_suffix
            else:
                name = f"{shard_name} #{index_string}"
                file_name_index = f"{shard_suffix}_{index_string}"
            rows.append(
                row_for(
                    conf=conf,
                    pieces=pieces,
                    name=name,
                    module_import_path=module_import_path,
                    file_name_index=file_name_index,
                    index=number,
                    index_string=index_string,
                    timeout_multiplier=timeout_multiplier,
                )
            )
    return rows


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

configuration: list[dict[str, Any]] = []

specified_defaults: dict[Path, dict[str, Any]] = {}
pytest_monitor_enabling_paths: list[Path] = []
defaults = directory_defaults()
plans: list[DirectoryPlan] = []

for path in test_paths:
    if path.is_dir():
        test_files = sorted(path.glob("test_*.py"))
        config_path = path
    else:
        test_files = [path]
        config_path = path.parent

    try:
        conf = update_config(defaults, dir_config(config_path))
    except SpecifiedDefaultsError as e:
        specified_defaults[root_path.joinpath(config_path, "config.py")] = e.overlap
        continue

    if conf["check_resource_usage"]:
        # NOTE: do not use until the hangs are fixed
        #       https://github.com/CFMTech/pytest-monitor/issues/53
        #       https://github.com/pythonprofilers/memory_profiler/issues/342
        pytest_monitor_enabling_paths.append(path)

    plans.append(
        DirectoryPlan(
            path=path,
            relative=path.relative_to(root_path).as_posix(),
            files=test_files,
            conf=conf,
        )
    )

pack_groups: list[list[str]] = list(module_dict(testconfig).get("matrix_packs", []))
pack_by_member: dict[str, int] = {}
if args.per == "directory":
    available = {plan.relative for plan in plans}
    for group in pack_groups:
        present = [member for member in group if member in available]
        missing = [member for member in group if member not in available]
        if len(present) > 0 and len(missing) > 0:
            msg = f"matrix pack group is missing directories: present={present} missing={missing}"
            raise Exception(msg)
        if len(present) != len(group) or len(group) == 0:
            continue
        members = [plan for plan in plans if plan.relative in set(group)]
        compatible_pack(members)
        group_index = len(set(pack_by_member.values()))
        for member in group:
            if member in pack_by_member:
                msg = f"{member} is listed in more than one matrix pack group"
                raise Exception(msg)
            pack_by_member[member] = group_index

emitted_packs: set[int] = set()
expected_repo_paths: list[str] = []

for plan in plans:
    expected_repo_paths.extend(test_file_ref(path).repo_path for path in plan.files)
    pack_index = pack_by_member.get(plan.relative)
    if pack_index is not None:
        if pack_index in emitted_packs:
            continue
        emitted_packs.add(pack_index)
        members = [candidate for candidate in plans if pack_by_member.get(candidate.relative) == pack_index]
        members.sort(key=lambda candidate: tests_import_path(candidate.path))
        module_import_path = "+".join(tests_import_path(member.path) for member in members)
        pieces = [test_file_ref(path).whole() for member in members for path in member.files]
        pieces.sort(key=lambda piece: piece.repo_path)
        conf = merged_pack_config([member.conf for member in members])
        configuration.extend(
            shard_rows(
                module_import_path=module_import_path,
                pieces_by_shard=[pieces],
                conf=conf,
                duplicates=args.duplicates,
                timeout_multiplier=args.timeout_multiplier,
            )
        )
        continue

    refs = [test_file_ref(path) for path in plan.files]
    shard_count = int(plan.conf["matrix_shards"]) if plan.path.is_dir() else 1
    weights = plan.conf.get("matrix_shard_weights") or None
    pieces_by_shard = matrix_shard.plan_shards(refs, shard_count, weights)
    module_import_path = tests_import_path(plan.path)
    configuration.extend(
        shard_rows(
            module_import_path=module_import_path,
            pieces_by_shard=pieces_by_shard,
            conf=plan.conf,
            duplicates=args.duplicates,
            timeout_multiplier=args.timeout_multiplier,
        )
    )

messages: list[str] = []

if len(specified_defaults) > 0:
    message = f"Found {len(specified_defaults)} directories with specified defaults"
    messages.append(message)
    log.error(f"{message}:")
    for path, overlap in sorted(specified_defaults.items()):
        log.error(f" {path} : {overlap}")

if len(pytest_monitor_enabling_paths) > 0:
    message = f"Found {len(pytest_monitor_enabling_paths)} directories with pytest-monitor enabled"
    messages.append(message)
    log.error(f"{message}:")
    for path in sorted(pytest_monitor_enabling_paths):
        log.error(f" {path}")

if len(messages) > 0:
    raise Exception("\n".join(messages))

if len(specified_defaults) == 0:
    matrix_shard.assert_file_partition(
        expected_repo_paths,
        [row["test_files"] for row in configuration],
        copies=args.duplicates,
    )

configuration_json = json.dumps(configuration)

for line in json.dumps(configuration, indent=2).splitlines():
    log.info(line)

print(f"{configuration_json}")
