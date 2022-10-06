from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import click

from chia.cmds.beta_funcs import (
    default_beta_root_path,
    prepare_chia_blockchain_log,
    prepare_logs,
    prepare_plotting_log,
    prompt_beta_warning,
    prompt_for_beta_path,
    prompt_for_metrics_log_interval,
    update_beta_config,
    validate_beta_path,
    validate_metrics_log_interval,
)
from chia.util.beta_metrics import metrics_log_interval_default
from chia.util.config import lock_and_load_config, save_config


def print_restart_warning() -> None:
    print("\nRestart the daemon and any running chia services for changes to take effect.")


@click.group("beta", hidden=True)
def beta_cmd() -> None:
    pass


@beta_cmd.command("configure", help="Configure the beta test mode parameters")
@click.option("-p", "--path", help="The beta mode root path", type=str, required=False)
@click.option("-i", "--interval", help="System metrics will be logged based on this interval", type=int, required=False)
@click.pass_context
def configure(ctx: click.Context, path: Optional[str], interval: Optional[int]) -> None:
    root_path = ctx.obj["root_path"]
    with lock_and_load_config(root_path, "config.yaml") as config:
        if "beta" not in config:
            raise click.ClickException("beta test mode is not enabled, enable it first with `chia beta enable`")

        # Adjust the path
        if path is None:
            beta_root_path = prompt_for_beta_path(Path(config["beta"].get("path", default_beta_root_path())))
        else:
            beta_root_path = Path(path)
            validate_beta_path(beta_root_path)

        # Adjust the metrics log interval
        if interval is None:
            metrics_log_interval = prompt_for_metrics_log_interval(
                int(config["beta"].get("metrics_log_interval", metrics_log_interval_default))
            )
        else:
            metrics_log_interval = interval
            try:
                validate_metrics_log_interval(metrics_log_interval)
            except ValueError as e:
                raise click.ClickException(str(e))

        update_beta_config(True, beta_root_path, metrics_log_interval, config)
        save_config(root_path, "config.yaml", config)

    print("\nbeta config updated")
    print_restart_warning()


@beta_cmd.command("enable", help="Enable beta test mode")
@click.option(
    "-f",
    "--force",
    help="Force accept the beta program warning",
    is_flag=True,
    default=False,
)
@click.option("-p", "--path", help="The beta mode root path", type=str, required=False)
@click.pass_context
def enable_cmd(ctx: click.Context, force: bool, path: Optional[str]) -> None:
    root_path = ctx.obj["root_path"]
    with lock_and_load_config(root_path, "config.yaml") as config:
        if config.get("beta", {}).get("enabled", False):
            raise click.ClickException("beta test mode is already enabled")

        if not force and not prompt_beta_warning():
            ctx.abort()

        # Use the existing beta path if there is one and no path was provided as parameter
        current_path = config.get("beta", {}).get("path")
        current_path = None if current_path is None else Path(current_path)

        if path is None and current_path is None:
            beta_root_path = prompt_for_beta_path(current_path or default_beta_root_path())
        else:
            beta_root_path = Path(path or current_path)
            validate_beta_path(beta_root_path)

        update_beta_config(True, beta_root_path, metrics_log_interval_default, config)
        save_config(root_path, "config.yaml", config)

    print(f"\nbeta test mode enabled with path {str(beta_root_path)!r}")
    print_restart_warning()


@beta_cmd.command("disable", help="Disable beta test mode")
@click.pass_context
def disable_cmd(ctx: click.Context) -> None:
    root_path = ctx.obj["root_path"]
    with lock_and_load_config(root_path, "config.yaml") as config:
        if not config.get("beta", {}).get("enabled", False):
            raise click.ClickException("beta test mode is not enabled")
        config["beta"]["enabled"] = False
        save_config(root_path, "config.yaml", config)

    print("\nbeta test mode disabled")
    print_restart_warning()


@beta_cmd.command("prepare_submission", help="Prepare the collected log data for submission")
@click.pass_context
def prepare_submission_cmd(ctx: click.Context) -> None:
    with lock_and_load_config(ctx.obj["root_path"], "config.yaml") as config:
        beta_root_path = config.get("beta", {}).get("path", None)
        if beta_root_path is None:
            raise click.ClickException("beta test mode not enabled. Run `chia beta enable` first.")
    beta_root_path = Path(beta_root_path)
    validate_beta_path(beta_root_path)
    available_results = sorted([path for path in beta_root_path.iterdir() if path.is_dir()])
    if len(available_results) == 0:
        raise click.ClickException(f"No beta logs found in {str(beta_root_path)!r}.")
    print("Available versions:")
    for i in range(len(available_results)):
        print(f"    [{i + 1}] {available_results[i].name}")

    user_input = input("Select the version you want to prepare for submission: ")
    try:
        if int(user_input) <= 0:
            raise IndexError()
        prepare_result = available_results[int(user_input) - 1]
    except IndexError:
        raise click.ClickException(f"Invalid choice: {user_input}")
    plotting_path = Path(prepare_result / "plotting")
    chia_blockchain_path = Path(prepare_result / "chia-blockchain")
    chia_logs = prepare_logs(plotting_path, prepare_chia_blockchain_log)
    plotting_logs = prepare_logs(chia_blockchain_path, prepare_plotting_log)

    submission_file_path = (
        prepare_result / f"submission_{prepare_result.name}__{datetime.now().strftime('%m_%d_%Y__%H_%M_%S')}.zip"
    )

    def add_files(paths: List[Path]) -> int:
        added = 0
        for path in paths:
            if path.name.startswith("."):
                continue
            zip_file.write(path, path.relative_to(prepare_result))
            added += 1
        return added

    with zipfile.ZipFile(submission_file_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        files_added = add_files(chia_logs) + add_files(plotting_logs)

    if files_added == 0:
        submission_file_path.unlink()
        message = f"No logs files found in {str(plotting_path)!r} and {str(chia_blockchain_path)!r}."
        raise click.ClickException(message)

    print(f"\nDone. You can find the prepared submission data in {submission_file_path}.")


@beta_cmd.command("status", help="Show the current beta configuration")
@click.pass_context
def status(ctx: click.Context) -> None:
    with lock_and_load_config(ctx.obj["root_path"], "config.yaml") as config:
        beta_config = config.get("beta")
        if beta_config is None:
            raise click.ClickException("beta test mode is not enabled, enable it first with `chia beta enable`")

    print(f"enabled: {beta_config['enabled']}")
    print(f"path: {beta_config['path']}")
    print(f"metrics log interval: {beta_config['metrics_log_interval']}s")
