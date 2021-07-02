import sys

from chia.util.keychain import Keychain, obtain_current_passphrase
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE
from getpass import getpass
from io import TextIOWrapper
from typing import Optional, Tuple

MIN_PASSPHRASE_LEN = 8
# Click drops leading dashes, and converts remaining dashes to underscores. e.g. --set-passphrase -> 'set_passphrase'
PASSPHRASE_CLI_OPTION_NAMES = ["keys_root_path", "set_passphrase", "passphrase_file", "current_passphrase_file"]


def remove_passphrase_options_from_cmd(cmd) -> None:
    # TODO: Click doesn't seem to have a great way of adding/removing params using an
    # existing command, and using the decorator-supported construction of options doesn't
    # allow for conditionally including options. Once keyring passphrase management is
    # rolled out to all platforms this can be removed.
    cmd.params = [param for param in cmd.params if param.name not in PASSPHRASE_CLI_OPTION_NAMES]


def verify_passphrase_meets_requirements(
    new_passphrase: str, confirmation_passphrase: str
) -> Tuple[bool, Optional[str]]:
    match = new_passphrase == confirmation_passphrase
    meets_len_requirement = len(new_passphrase) >= MIN_PASSPHRASE_LEN

    if match and meets_len_requirement:
        return True, None
    elif not match:
        return False, "Passphrases do not match"
    elif not meets_len_requirement:
        return False, f"Minimum passphrase length is {MIN_PASSPHRASE_LEN}"
    else:
        raise Exception("Unexpected passphrase verification case")


def tidy_passphrase(passphrase: str) -> str:
    """
    Perform any string processing we want to apply to the entered passphrase.
    Currently we strip leading/trailing whitespace.
    """
    return passphrase.strip()


def prompt_for_new_passphrase() -> str:
    if MIN_PASSPHRASE_LEN > 0:
        print(f"\nPassphrases must be {MIN_PASSPHRASE_LEN} or more characters in length")
    while True:
        passphrase = tidy_passphrase(getpass("New Passphrase: "))
        confirmation = tidy_passphrase(getpass("Confirm Passphrase: "))

        valid_passphrase, error_msg = verify_passphrase_meets_requirements(passphrase, confirmation)

        if valid_passphrase:
            return passphrase
        elif error_msg:
            print(f"{error_msg}\n")


def read_passphrase_from_file(passphrase_file: TextIOWrapper) -> str:
    passphrase = tidy_passphrase(passphrase_file.read())
    passphrase_file.close()
    return passphrase


def initialize_passphrase() -> None:
    if Keychain.has_master_passphrase():
        print("Keyring is already protected by a passphrase")
        print("\nUse 'chia passphrase set' or 'chia passphrase remove' to update or remove your passphrase")
        sys.exit(1)

    # We'll rely on Keyring initialization to leverage the cached passphrase for
    # bootstrapping the keyring encryption process
    print("Setting keyring passphrase")
    passphrase = None
    if Keychain.has_cached_passphrase():
        passphrase = Keychain.get_cached_master_passphrase()

    if not passphrase or passphrase == DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE:
        passphrase = prompt_for_new_passphrase()

    Keychain.set_master_password(current_password=None, new_password=passphrase)


def set_or_update_passphrase(passphrase: Optional[str], current_passphrase: Optional[str]) -> None:
    # Prompt for the current passphrase, if necessary
    if Keychain.has_master_passphrase():
        # Try the default passphrase first
        if Keychain.master_passphrase_is_valid(DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE):
            current_passphrase = DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE

        if not current_passphrase:
            try:
                current_passphrase = obtain_current_passphrase("Current Passphrase: ")
            except Exception as e:
                print(f"Unable to confirm current passphrase: {e}")
                sys.exit(1)

    new_passphrase = passphrase
    try:
        # Prompt for the new passphrase, if necessary
        if not new_passphrase:
            new_passphrase = prompt_for_new_passphrase()

        if new_passphrase == current_passphrase:
            raise ValueError("passphrase is unchanged")

        Keychain.set_master_password(current_password=current_passphrase, new_password=new_passphrase)
    except Exception as e:
        print(f"Unable to set or update passphrase: {e}")


def remove_passphrase(current_passphrase: Optional[str]) -> None:
    if not Keychain.has_master_passphrase():
        print("Passphrase is not currently set")
    else:
        # Try the default passphrase first
        if Keychain.master_passphrase_is_valid(DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE):
            current_passphrase = DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE

        # Prompt for the current passphrase, if necessary
        if not current_passphrase:
            try:
                current_passphrase = obtain_current_passphrase("Current Passphrase: ")
            except Exception as e:
                print(f"Unable to confirm current passphrase: {e}")

        try:
            Keychain.remove_master_password(current_passphrase)
        except Exception as e:
            print(f"Unable to remove passphrase: {e}")


def cache_passphrase(passphrase: str) -> None:
    Keychain.set_cached_master_password(passphrase)
