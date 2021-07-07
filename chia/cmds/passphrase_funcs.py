import sys

from chia.daemon.client import connect_to_daemon_and_validate
from chia.util.keychain import Keychain, obtain_current_passphrase
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE
from getpass import getpass
from io import TextIOWrapper
from pathlib import Path
from typing import Optional, Tuple

MIN_PASSPHRASE_LEN = 8
# Click drops leading dashes, and converts remaining dashes to underscores. e.g. --set-passphrase -> 'set_passphrase'
PASSPHRASE_CLI_OPTION_NAMES = ["keys_root_path", "set_passphrase", "passphrase_file", "current_passphrase_file"]


def remove_passphrase_options_from_cmd(cmd) -> None:
    """
    Filters-out passphrase optiosn from a given Click command object
    """
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

    if not passphrase or passphrase == default_passphrase():
        passphrase = prompt_for_new_passphrase()

    Keychain.set_master_passphrase(current_passphrase=None, new_passphrase=passphrase)


def set_or_update_passphrase(passphrase: Optional[str], current_passphrase: Optional[str]) -> bool:
    # Prompt for the current passphrase, if necessary
    if Keychain.has_master_passphrase():
        # Try the default passphrase first
        if using_default_passphrase():
            current_passphrase = default_passphrase()

        if not current_passphrase:
            try:
                current_passphrase = obtain_current_passphrase("Current Passphrase: ")
            except Exception as e:
                print(f"Unable to confirm current passphrase: {e}")
                sys.exit(1)

    success = False
    new_passphrase = passphrase
    try:
        # Prompt for the new passphrase, if necessary
        if not new_passphrase:
            new_passphrase = prompt_for_new_passphrase()

        if new_passphrase == current_passphrase:
            raise ValueError("passphrase is unchanged")

        Keychain.set_master_passphrase(current_passphrase=current_passphrase, new_passphrase=new_passphrase)
        success = True
    except Exception as e:
        print(f"Unable to set or update passphrase: {e}")
        success = False

    return success


def remove_passphrase(current_passphrase: Optional[str]) -> bool:
    """
    Removes the user's keyring passphrase. The keyring will be re-encrypted to the default passphrase.
    """
    success = False

    if not Keychain.has_master_passphrase() or using_default_passphrase():
        print("Passphrase is not currently set")
        success = False
    else:
        # Try the default passphrase first
        if using_default_passphrase():
            current_passphrase = default_passphrase()

        # Prompt for the current passphrase, if necessary
        if not current_passphrase:
            try:
                current_passphrase = obtain_current_passphrase("Current Passphrase: ")
            except Exception as e:
                print(f"Unable to confirm current passphrase: {e}")
                success = False

        if current_passphrase:
            try:
                Keychain.remove_master_passphrase(current_passphrase)
                success = True
            except Exception as e:
                print(f"Unable to remove passphrase: {e}")
                success = False

    return success


def cache_passphrase(passphrase: str) -> None:
    Keychain.set_cached_master_passphrase(passphrase)


def get_current_passphrase() -> Optional[str]:
    if not Keychain.has_master_passphrase():
        return None

    current_passphrase = None
    if using_default_passphrase():
        current_passphrase = default_passphrase()
    else:
        try:
            current_passphrase = obtain_current_passphrase()
        except Exception as e:
            print(f"Unable to confirm current passphrase: {e}")
            raise e

    return current_passphrase


def default_passphrase() -> str:
    return DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE


def using_default_passphrase() -> bool:
    if not Keychain.has_master_passphrase():
        return False

    return Keychain.master_passphrase_is_valid(default_passphrase())


async def async_update_daemon_passphrase_cache_if_running(root_path: Path) -> None:
    new_passphrase = Keychain.get_cached_master_passphrase()
    assert new_passphrase is not None

    daemon = None
    try:
        daemon = await connect_to_daemon_and_validate(root_path, quiet=True)
        if daemon:
            response = await daemon.unlock_keyring(new_passphrase)

            if not response:
                raise Exception("daemon didn't respond")

            if response["data"].get("success", False) is False:
                error = response["data"].get("error", "unknown error")
                raise Exception(error)
    except Exception as e:
        print(f"Failed to notify daemon of updated keyring passphrase: {e}")

    if daemon:
        await daemon.close()
