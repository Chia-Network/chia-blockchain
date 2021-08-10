import asyncio
import click
import sys
from io import TextIOWrapper
from typing import Optional


@click.group("passphrase", short_help="Manage your keyring passphrase")
def passphrase_cmd():
    pass


@passphrase_cmd.command(
    "set",
    help="""Sets or updates the keyring passphrase. If --passphrase-file and/or --current-passphrase-file options are provided,
            the passphrases will be read from the specified files. Otherwise, a prompt will be provided to enter the
            passphrase.""",
    short_help="Set or update the keyring passphrase",
)
@click.option("--passphrase-file", type=click.File("r"), help="File or descriptor to read the passphrase from")
@click.option(
    "--current-passphrase-file", type=click.File("r"), help="File or descriptor to read the current passphrase from"
)
@click.pass_context
def set_cmd(
    ctx: click.Context, passphrase_file: Optional[TextIOWrapper], current_passphrase_file: Optional[TextIOWrapper]
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
            success = set_or_update_passphrase(passphrase=new_passphrase, current_passphrase=current_passphrase)
    else:
        success = set_or_update_passphrase(passphrase=None, current_passphrase=current_passphrase)

    if success:
        # Attempt to update the daemon's passphrase cache
        sys.exit(
            asyncio.get_event_loop().run_until_complete(
                async_update_daemon_passphrase_cache_if_running(ctx.obj["root_path"])
            )
        )


@passphrase_cmd.command(
    "remove",
    help="""Remove the keyring passphrase. If the --current-passphrase-file option is provided, the passphrase will be read from
            the specified file. Otherwise, a prompt will be provided to enter the passphrase.""",
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
        sys.exit(
            asyncio.get_event_loop().run_until_complete(
                async_update_daemon_passphrase_cache_if_running(ctx.obj["root_path"])
            )
        )
