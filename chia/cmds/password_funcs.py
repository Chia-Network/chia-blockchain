import sys

from chia.util.keychain import Keychain, obtain_current_password
from chia.util.keyring_wrapper import DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD
from getpass import getpass
from io import TextIOWrapper
from typing import Optional, Tuple

MIN_PASSWORD_LEN = 8
# Click drops leading dashes, and converts remaining dashes to underscores. e.g. --set-password -> 'set_password'
PASSWORD_CLI_OPTION_NAMES = ["set_password", "password_file", "current_password_file"]


def supports_keyring_password() -> bool:
    from sys import platform

    return platform == "linux"


def remove_passwords_options_from_cmd(cmd) -> None:
    # TODO: Click doesn't seem to have a great way of adding/removing params using an
    # existing command, and using the decorator-supported construction of options doesn't
    # allow for conditionally including options. Once keyring password management is
    # rolled out to all platforms this can be removed.
    cmd.params = [param for param in cmd.params if param.name not in PASSWORD_CLI_OPTION_NAMES]


def verify_password_meets_requirements(new_password: str, confirmation_password: str) -> Tuple[bool, Optional[str]]:
    match = new_password == confirmation_password
    meets_len_requirement = len(new_password) >= MIN_PASSWORD_LEN

    if match and meets_len_requirement:
        return True, None
    elif not match:
        return False, "Passwords do not match"
    elif not meets_len_requirement:
        return False, f"Minimum password length is {MIN_PASSWORD_LEN}"
    else:
        raise Exception("Unexpected password verification case")


def tidy_password(password: str) -> str:
    """
    Perform any string processing we want to apply to the entered password.
    Currently we strip leading/trailing whitespace.
    """
    return password.strip()


def prompt_for_new_password() -> str:
    if MIN_PASSWORD_LEN > 0:
        print(f"\nPasswords must be {MIN_PASSWORD_LEN} or more characters in length")
    while True:
        password = tidy_password(getpass("New Password: "))
        confirmation = tidy_password(getpass("Confirm Password: "))

        valid_password, error_msg = verify_password_meets_requirements(password, confirmation)

        if valid_password:
            return password
        elif error_msg:
            print(f"{error_msg}\n")


def read_password_from_file(password_file: TextIOWrapper) -> str:
    password = tidy_password(password_file.read())
    password_file.close()
    return password


def initialize_password() -> None:
    if Keychain.has_master_password():
        print("Keyring is already protected by a password")
        print("\nUse 'chia password set' or 'chia password remove' to update or remove your password")
        sys.exit(1)

    # We'll rely on Keyring initialization to leverage the cached password for
    # bootstrapping the keyring encryption process
    print("Setting keyring password")
    password = None
    if Keychain.has_cached_password():
        password = Keychain.get_cached_master_password()

    if not password or password == DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD:
        password = prompt_for_new_password()

    Keychain.set_master_password(current_password=None, new_password=password)


def set_or_update_password(password: Optional[str], current_password: Optional[str]) -> None:
    # Prompt for the current password, if necessary
    if Keychain.has_master_password():
        # Try the default password first
        if Keychain.master_password_is_valid(DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD):
            current_password = DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD

        if not current_password:
            try:
                current_password = obtain_current_password("Current Password: ")
            except Exception as e:
                print(f"Unable to confirm current password: {e}")
                sys.exit(1)

    new_password = password
    try:
        # Prompt for the new password, if necessary
        if not new_password:
            new_password = prompt_for_new_password()

        if new_password == current_password:
            raise ValueError("password is unchanged")

        Keychain.set_master_password(current_password=current_password, new_password=new_password)
    except Exception as e:
        print(f"Unable to set or update password: {e}")


def remove_password(current_password: Optional[str]) -> None:
    if not Keychain.has_master_password():
        print("Password is not currently set")
    else:
        # Try the default password first
        if Keychain.master_password_is_valid(DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD):
            current_password = DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD

        # Prompt for the current password, if necessary
        if not current_password:
            try:
                current_password = obtain_current_password("Current Password: ")
            except Exception as e:
                print(f"Unable to confirm current password: {e}")

        try:
            Keychain.remove_master_password(current_password)
        except Exception as e:
            print(f"Unable to remove password: {e}")


def cache_password(password: str) -> None:
    Keychain.set_cached_master_password(password)
