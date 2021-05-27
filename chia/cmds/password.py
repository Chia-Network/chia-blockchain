import click
from io import TextIOWrapper
from typing import Optional


@click.group("password", short_help="Manage your keyring password")
def password_cmd():
    pass


@password_cmd.command(
    "set",
    help="""Sets or updates the keyring password. If --password-file and/or --current-password-file options are provided,
            the passwords will be read from the specified files. Otherwise, a prompt will be provided to enter the
            password.""",
    short_help="Set or update the keyring password",
)
@click.option("--password-file", type=click.File("r"), help="File or descriptor to read the password from")
@click.option(
    "--current-password-file", type=click.File("r"), help="File or descriptor to read the current password from"
)
def set_cmd(password_file: Optional[TextIOWrapper], current_password_file: Optional[TextIOWrapper]) -> None:
    from .password_funcs import read_password_from_file, set_or_update_password, verify_password_meets_requirements

    current_password = None
    if current_password_file:
        current_password = read_password_from_file(current_password_file)

    if password_file:
        new_password = None
        try:
            # Read the password from a file and verify it
            new_password = read_password_from_file(password_file)
            valid_password, error_msg = verify_password_meets_requirements(
                new_password, new_password
            )  # new_password provided for both args since we don't have a separate confirmation password

            if not valid_password:
                raise ValueError(f"{error_msg}")
        except ValueError as e:
            print(f"Unable to set password: {e}")
        except Exception as e:
            print(f"Failed to read password: {e}")
        else:
            # Interactively prompt for the current password (if set)
            set_or_update_password(password=new_password, current_password=current_password)
    else:
        set_or_update_password(password=None, current_password=current_password)


@password_cmd.command(
    "remove",
    help="""Remove the keyring password. If the --current-password-file option is provided, the password will be read from
            the specified file. Otherwise, a prompt will be provided to enter the password.""",
    short_help="Remove the keyring password",
)
@click.option(
    "--current-password-file", type=click.File("r"), help="File or descriptor to read the current password from"
)
def remove_cmd(current_password_file: Optional[TextIOWrapper]) -> None:
    from .password_funcs import read_password_from_file, remove_password

    current_password = None
    if current_password_file:
        current_password = read_password_from_file(current_password_file)

    remove_password(current_password)
