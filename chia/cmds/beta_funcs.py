from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from chia.util.beta_metrics import metrics_log_interval_max, metrics_log_interval_min
from chia.util.chia_logging import get_beta_logging_config
from chia.util.errors import InvalidPathError
from chia.util.misc import format_bytes, prompt_yes_no, validate_directory_writable


def default_beta_root_path() -> Path:
    return Path(os.path.expanduser(os.getenv("CHIA_BETA_ROOT", "~/chia-beta-test"))).resolve()


def warn_if_beta_enabled(config: Dict[str, Any]) -> None:
    if config.get("beta", {}).get("enabled", False):
        print("\nWARNING: beta test mode is enabled. Run `chia beta disable` if this is unintentional.\n")


def prompt_beta_warning() -> bool:
    logging_config = get_beta_logging_config()
    # The `/ 5` is just a rough estimation for `gzip` being used by the log rotation in beta mode. It was like
    # 7-10x compressed in example tests with 2MB files.
    min_space = format_bytes(int(logging_config["log_maxfilesrotation"] * logging_config["log_maxbytesrotation"] / 5))
    return prompt_yes_no(
        f"\nWARNING: Enabling the beta test mode increases disk writes and may lead to {min_space} of "
        "extra logfiles getting stored on your disk. This should only be done if you are part of the beta test "
        "program.\n\nDo you really want to enable the beta test mode?"
    )


def prompt_for_beta_path(default_path: Path) -> Path:
    path: Optional[Path] = None
    for _ in range(3):
        user_input = input(
            "\nEnter a directory where the beta test logs can be stored or press enter to use the default "
            f"[{str(default_path)}]:"
        )
        test_path = Path(user_input) if user_input else default_path
        if not test_path.is_dir() and prompt_yes_no(
            f"\nDirectory {str(test_path)!r} doesn't exist.\n\nDo you want to create it?"
        ):
            test_path.mkdir(parents=True)

        try:
            validate_directory_writable(test_path)
        except InvalidPathError as e:
            print(str(e))
            continue

        path = test_path
        break

    if path is None:
        sys.exit("Aborted!")
    else:
        return path


def prompt_for_metrics_log_interval(default_interval: int) -> int:
    interval: Optional[int] = None
    for _ in range(3):
        user_input = input(
            "\nEnter a number of seconds as interval in which analytics getting logged, press enter to use the default "
            f"[{str(default_interval)}]:"
        )
        test_interval = int(user_input) if user_input else default_interval

        try:
            validate_metrics_log_interval(test_interval)
        except ValueError as e:
            print("\nERROR: " + str(e))
            continue

        interval = test_interval
        break

    if interval is None:
        sys.exit("Aborted!")
    else:
        return interval


def update_beta_config(enabled: bool, path: Path, metrics_log_interval: int, config: Dict[str, Any]) -> None:
    if "beta" not in config:
        config["beta"] = {}

    config["beta"].update(
        {
            "enabled": enabled,
            "path": str(path),
            "metrics_log_interval": metrics_log_interval,
        }
    )


def validate_beta_path(beta_root_path: Path) -> None:
    try:
        validate_directory_writable(beta_root_path)
    except InvalidPathError as e:
        sys.exit(str(e))


def validate_metrics_log_interval(interval: int) -> None:
    if interval < metrics_log_interval_min or interval > metrics_log_interval_max:
        raise ValueError(f"Must be in the range of {metrics_log_interval_min}s to {metrics_log_interval_max}s.")


def prepare_plotting_log(path: Path) -> None:
    # TODO: Do stuff we want to do with the logs before submission. Maybe even just fully parse them and
    #  create some final result files and zip them instead of just the logs.
    print(f"  - {path.name}")


def prepare_chia_blockchain_log(path: Path) -> None:
    # TODO: Do stuff we want to do with the logs before submission. Maybe even just fully parse them and
    #  create some final result files and zip them instead of just the logs.
    print(f"  - {path.name}")


def prepare_logs(prepare_path: Path, prepare_callback: Callable[[Path], None]) -> List[Path]:
    result = [path for path in prepare_path.iterdir()] if prepare_path.exists() else []
    if len(result):
        print(f"\nPreparing {prepare_path.name!r} logs:")
        for log in result:
            if log.name.startswith("."):
                continue
            prepare_callback(log)

    return result
