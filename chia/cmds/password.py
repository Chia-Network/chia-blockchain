import click
from io import TextIOWrapper


def realize_password(password: str, password_file: TextIOWrapper) -> str:
    password_value = password
    if password_value == None and password_file != None:
        password_value = password_file.read().rstrip()
        password_file.close()
    return password_value

@click.group("password", short_help="Manage your keyring password")
def password_cmd():
    pass

@password_cmd.command("set", short_help="Set or update the keyring password")
@click.option('--password', prompt=True, prompt_required=False, hide_input=True, help="Password used to secure your keyring contents")
@click.option('--password-file', type=click.File('r'), help="File or descriptor to read the password from")
def set_cmd(password: str, password_file: TextIOWrapper) -> None:
    password = realize_password(password, password_file)

@password_cmd.command("remove", short_help="Remove the keyring password")
@click.option('--current-password', prompt=True, prompt_required=False, hide_input=True, help="Current password used to secure your keyring contents")
@click.option('--current-password-file', type=click.File('r'), help="File or descriptor to read the current password from")
def remove_cmd(current_password: str, current_password_file: TextIOWrapper) -> None:
    password = realize_password(current_password, current_password_file)
