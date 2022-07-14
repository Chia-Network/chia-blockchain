import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from chia.util.chia_logging import get_beta_logging_config
from chia.util.config import lock_and_load_config, save_config
from chia.util.misc import format_bytes, prompt_yes_no


def warn_if_beta(config: Dict[str, Any]) -> None:
    if "beta" in config:
        print("\nWARNING: beta test mode is enabled. Run `chia beta disable` if this is unintentional.\n")


def configure_beta_test_mode(root_path: Path, enable: bool) -> None:
    with lock_and_load_config(root_path, "config.yaml") as config:
        changed = False
        result = "NOT ACTIVE"
        if enable:
            if "beta" in config:
                sys.exit("beta test mode is already enabled. Disable it first with `chia beta disable`.")
            logging_config = get_beta_logging_config()
            # The `/ 5` is just a rough estimation for `gzip` being used by the log rotation in beta mode. It was like
            # 7-10x compressed in example tests with 2MB files.
            min_space = format_bytes(
                int(logging_config["log_maxfilesrotation"] * logging_config["log_maxbytesrotation"] / 5)
            )
            print(
                f"\nWARNING: Enabling the beta test mode increases disk writes and may lead to {min_space} of "
                "extra logfiles getting stored on your disk. This should only be done if you are part of the beta test "
                "program at: https://chia.net/beta-test\n"
            )
            if prompt_yes_no("Do you really want to enable the beta test mode?"):
                default_path = os.path.expanduser("~/chia-beta-test")
                beta_path: Optional[str] = None
                while beta_path is None:
                    user_input = input(
                        "\nFill in a custom directory for the beta test logs or press enter to use the default "
                        f"[{default_path}]:"
                    )
                    if user_input:
                        if not Path(user_input).is_dir():
                            print(f"Directory {user_input!r} doesn't exist.")
                            continue
                        beta_path = user_input
                    else:
                        beta_path = default_path

                config["beta"] = {
                    "path": beta_path,
                }
                result = "ENABLED"
                changed = True
            else:
                print("Aborted!")
                return
        elif "beta" in config:
            del config["beta"]
            result = "DISABLED"
            changed = True

        print(f"\nbeta test mode: {result}\n")

        if changed:
            save_config(root_path, "config.yaml", config)
            print("Restart the daemon and any running chia services for changes to take effect.")


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


def prepare_submission(root_path: Path) -> None:
    with lock_and_load_config(root_path, "config.yaml") as config:
        if "beta" not in config:
            sys.exit("beta test mode not enabled. Run `chia beta enable` first.")
        beta_path = Path(config["beta"]["path"])
        available_results = [path for path in Path(beta_path).iterdir() if path.is_dir()]
        if len(available_results) == 0:
            sys.exit(f"No beta logs found in {beta_path}.")
        print("Available versions:")
        for i in range(len(available_results)):
            print(f"    [{i + 1}] {available_results[i].name}")

        user_input = input("Select the version you want to prepare for submission: ")
        try:
            prepare_result = available_results[int(user_input) - 1]
        except Exception:
            sys.exit(f"Invalid choice: {user_input!r}")

        chia_logs = prepare_logs(Path(prepare_result / "plotting"), prepare_chia_blockchain_log)
        plotting_logs = prepare_logs(Path(prepare_result / "chia-blockchain"), prepare_plotting_log)

        submission_file_path = (
            prepare_result / f"submission_{prepare_result.name}__{datetime.now().strftime('%m_%d_%Y__%H_%M_%S')}.zip"
        )

        def add_files(paths: List[Path]) -> None:
            for path in paths:
                if path.name.startswith("."):
                    continue
                zip_file.write(path, path.relative_to(prepare_result))

        with zipfile.ZipFile(submission_file_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            add_files(chia_logs)
            add_files(plotting_logs)
        print(f"\nDone. You can find the prepared submission data in {submission_file_path}.")
