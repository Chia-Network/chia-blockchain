import click
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
def set_cmd(passphrase_file: Optional[TextIOWrapper], current_passphrase_file: Optional[TextIOWrapper]) -> None:
    from .passphrase_funcs import read_password_from_file, set_or_update_password, verify_password_meets_requirements

    current_passphrase = None
    if current_passphrase_file:
        current_passphrase = read_password_from_file(current_passphrase_file)

    if passphrase_file:
        new_passphrase = None
        try:
            # Read the passphrase from a file and verify it
            new_passphrase = read_password_from_file(passphrase_file)
            valid_passphrase, error_msg = verify_password_meets_requirements(
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
            set_or_update_password(password=new_passphrase, current_password=current_passphrase)
    else:
        set_or_update_password(password=None, current_password=current_passphrase)


@passphrase_cmd.command(
    "remove",
    help="""Remove the keyring passphrase. If the --current-passphrase-file option is provided, the passphrase will be read from
            the specified file. Otherwise, a prompt will be provided to enter the passphrase.""",
    short_help="Remove the keyring passphrase",
)
@click.option(
    "--current-passphrase-file", type=click.File("r"), help="File or descriptor to read the current passphrase from"
)
def remove_cmd(current_passphrase_file: Optional[TextIOWrapper]) -> None:
    from .passphrase_funcs import read_password_from_file, remove_password

    current_passphrase = None
    if current_passphrase_file:
        current_passphrase = read_password_from_file(current_passphrase_file)

    remove_password(current_passphrase)
