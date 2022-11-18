from __future__ import annotations

import asyncio
import sys
from io import TextIOWrapper
from typing import Optional

import click

from chia.util.config import load_config


@click.group("passphrase", short_help="Manage your keyring passphrase")
def passphrase_cmd():
    pass


@passphrase_cmd.command(
    "set",
    help="""Sets or updates the keyring passphrase. If --passphrase-file and/or --current-passphrase-file options are
            provided, the passphrases will be read from the specified files. Otherwise, a prompt will be provided to
            enter the passphrase.""",
    short_help="Set or update the keyring passphrase",
)
@click.option("--passphrase-file", type=click.File("r"), help="File or descriptor to read the passphrase from")
@click.option(
    "--current-passphrase-file", type=click.File("r"), help="File or descriptor to read the current passphrase from"
)
@click.option("--hint", type=str, help="Passphrase hint")
@click.pass_context
def set_cmd(
    ctx: click.Context,
    passphrase_file: Optional[TextIOWrapper],
    current_passphrase_file: Optional[TextIOWrapper],
    hint: Optional[str],
) -> None:
    from .passphrase_funcs import (
        async_update_daemon_passphrase_cache_if_running,
        read_passphrase_from_file,
        set_or_update_passphrase,
        verify_passphrase_meets_requirements,
    )

    success: bool = False
    current_passphrase: Optional[str] = None
    if current_passphrase_file is not None:
        current_passphrase = read_passphrase_from_file(current_passphrase_file)

    if passphrase_file is not None:
        try:
            # Read the passphrase from a file and verify it
            new_passphrase: str = read_passphrase_from_file(passphrase_file)
            valid_passphrase, error_msg = verify_passphrase_meets_requirements(
                new_passphrase, new_passphrase
            )  # new_passphrase provided for both args since we don't have a separate confirmation passphrase

            if not valid_passphrase:
                raise ValueError(f"{error_msg}")
        except ValueError as e:
            print(f"Unable to set passphrase: {e}")
        except Exception as e:
            print(f"Failed to read passphrase: {e}")
        else:
            # Interactively prompt for the current passphrase (if set)
            success = set_or_update_passphrase(
                passphrase=new_passphrase, current_passphrase=current_passphrase, hint=hint
            )
    else:
        success = set_or_update_passphrase(passphrase=None, current_passphrase=current_passphrase, hint=hint)

    if success:
        # Attempt to update the daemon's passphrase cache
        root_path = ctx.obj["root_path"]
        config = load_config(root_path, "config.yaml")
        sys.exit(asyncio.run(async_update_daemon_passphrase_cache_if_running(root_path, config)))


@passphrase_cmd.command(
    "remove",
    help="""Remove the keyring passphrase. If the --current-passphrase-file option is provided, the passphrase will be
            read from the specified file. Otherwise, a prompt will be provided to enter the passphrase.""",
    short_help="Remove the keyring passphrase",
)
@click.option(
    "--current-passphrase-file", type=click.File("r"), help="File or descriptor to read the current passphrase from"
)
@click.pass_context
def remove_cmd(ctx: click.Context, current_passphrase_file: Optional[TextIOWrapper]) -> None:
    from .passphrase_funcs import (
        async_update_daemon_passphrase_cache_if_running,
        read_passphrase_from_file,
        remove_passphrase,
    )

    current_passphrase: Optional[str] = None
    if current_passphrase_file is not None:
        current_passphrase = read_passphrase_from_file(current_passphrase_file)

    if remove_passphrase(current_passphrase):
        # Attempt to update the daemon's passphrase cache
        root_path = ctx.obj["root_path"]
        config = load_config(root_path, "config.yaml")
        sys.exit(asyncio.run(async_update_daemon_passphrase_cache_if_running(root_path, config)))


@passphrase_cmd.group("hint", short_help="Manage the optional keyring passphrase hint")
def hint_cmd() -> None:
    pass


@hint_cmd.command("display", short_help="Display the keyring passphrase hint")
def display_hint():
    from .passphrase_funcs import display_passphrase_hint

    display_passphrase_hint()


@hint_cmd.command("set", short_help="Set or update the keyring passphrase hint")
@click.argument("hint", nargs=1)
def set_hint(hint):
    from .passphrase_funcs import set_passphrase_hint

    set_passphrase_hint(hint)


@hint_cmd.command("remove", short_help="Remove the keyring passphrase hint")
def remove_hint():
    from .passphrase_funcs import remove_passphrase_hint

    remove_passphrase_hint()
