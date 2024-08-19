from __future__ import annotations

import os
import sys
import time
from getpass import getpass
from io import TextIOWrapper
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import colorama

from chia.cmds.cmds_util import prompt_yes_no
from chia.daemon.client import acquire_connection_to_daemon
from chia.util.errors import KeychainMaxUnlockAttempts
from chia.util.keychain import Keychain, supports_os_passphrase_storage
from chia.util.keyring_wrapper import DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE, KeyringWrapper

DEFAULT_PASSPHRASE_PROMPT = (
    colorama.Fore.YELLOW + colorama.Style.BRIGHT + "(Unlock Keyring)" + colorama.Style.RESET_ALL + " Passphrase: "
)  # noqa: E501
FAILED_ATTEMPT_DELAY = 0.5
MAX_RETRIES = 3
SAVE_MASTER_PASSPHRASE_WARNING = (
    colorama.Fore.YELLOW
    + colorama.Style.BRIGHT
    + "\n!!! SECURITY WARNING !!!\n"
    + colorama.Style.RESET_ALL
    + "Other processes may be able to access your saved passphrase, possibly exposing your private keys.\n"
    + "You should not save your passphrase unless you fully trust your environment.\n"
)


def obtain_current_passphrase(prompt: str = DEFAULT_PASSPHRASE_PROMPT, use_passphrase_cache: bool = False) -> str:
    """
    Obtains the master passphrase for the keyring, optionally using the cached
    value (if previously set). If the passphrase isn't already cached, the user is
    prompted interactively to enter their passphrase a max of MAX_RETRIES times
    before failing.
    """

    if use_passphrase_cache:
        passphrase, validated = KeyringWrapper.get_shared_instance().get_cached_master_passphrase()
        if passphrase:
            # If the cached passphrase was previously validated, we assume it's... valid
            if validated:
                return passphrase

            # Cached passphrase needs to be validated
            if KeyringWrapper.get_shared_instance().master_passphrase_is_valid(passphrase):
                KeyringWrapper.get_shared_instance().set_cached_master_passphrase(passphrase, validated=True)
                return passphrase
            else:
                # Cached passphrase is bad, clear the cache
                KeyringWrapper.get_shared_instance().set_cached_master_passphrase(None)

    # Prompt interactively with up to MAX_RETRIES attempts
    for i in range(MAX_RETRIES):
        colorama.init()

        passphrase = prompt_for_passphrase(prompt)

        if KeyringWrapper.get_shared_instance().master_passphrase_is_valid(passphrase):
            # If using the passphrase cache, and the user inputted a passphrase, update the cache
            if use_passphrase_cache:
                KeyringWrapper.get_shared_instance().set_cached_master_passphrase(passphrase, validated=True)
            return passphrase

        time.sleep(FAILED_ATTEMPT_DELAY)
        print("Incorrect passphrase\n")
    raise KeychainMaxUnlockAttempts()


def verify_passphrase_meets_requirements(
    new_passphrase: str, confirmation_passphrase: str
) -> Tuple[bool, Optional[str]]:
    match = new_passphrase == confirmation_passphrase
    min_length = Keychain.minimum_passphrase_length()
    meets_len_requirement = len(new_passphrase) >= min_length

    if match and meets_len_requirement:
        return True, None
    elif not match:
        return False, "Passphrases do not match"
    elif not meets_len_requirement:
        return False, f"Minimum passphrase length is {min_length}"
    else:
        raise Exception("Unexpected passphrase verification case")


def prompt_for_passphrase(prompt: str) -> str:
    if sys.platform == "win32" or sys.platform == "cygwin":
        print(prompt, end="", flush=True)
        prompt = ""
    return getpass(prompt)


def prompt_to_save_passphrase() -> bool:
    save: bool = False

    try:
        if supports_os_passphrase_storage():
            location: Optional[str] = None
            warning: Optional[str] = None

            if sys.platform == "darwin":
                location = "macOS Keychain"
                warning = SAVE_MASTER_PASSPHRASE_WARNING
            elif sys.platform == "win32" or sys.platform == "cygwin":
                location = "Windows Credential Manager"
                warning = SAVE_MASTER_PASSPHRASE_WARNING

            if location is None:
                raise ValueError("OS-specific credential store not specified")

            print(
                "\n"
                "Your passphrase can be stored in your system's secure credential store. "
                "Other Chia processes will be able to access your keys without prompting for your passphrase."
            )
            if warning is not None:
                colorama.init()

                print(warning)
            save = prompt_yes_no(f"Would you like to save your passphrase to the {location}?")

    except Exception as e:
        print(f"Caught exception: {e}")
        return False

    return save


def prompt_for_new_passphrase() -> Tuple[str, bool]:
    min_length: int = Keychain.minimum_passphrase_length()
    if min_length > 0:
        n = min_length
        print(f"\nPassphrases must be {n} or more characters in length")  # lgtm [py/clear-text-logging-sensitive-data]
    while True:
        passphrase: str = getpass("New Passphrase: ")
        confirmation: str = getpass("Confirm Passphrase: ")
        save_passphrase: bool = False

        valid_passphrase, error_msg = verify_passphrase_meets_requirements(passphrase, confirmation)

        if valid_passphrase:
            if supports_os_passphrase_storage():
                save_passphrase = prompt_to_save_passphrase()

            return passphrase, save_passphrase
        elif error_msg:
            print(f"{error_msg}\n")  # lgtm [py/clear-text-logging-sensitive-data]


def read_passphrase_from_file(passphrase_file: TextIOWrapper) -> str:
    passphrase = passphrase_file.read().rstrip(os.environ.get("CHIA_PASSPHRASE_STRIP_TRAILING_CHARS", "\r\n"))
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
    passphrase: Optional[str] = None
    # save_passphrase indicates whether the passphrase should be saved in the
    # macOS Keychain or Windows Credential Manager
    save_passphrase: bool = False

    if Keychain.has_cached_passphrase():
        passphrase = Keychain.get_cached_master_passphrase()

    if not passphrase or passphrase == default_passphrase():
        passphrase, save_passphrase = prompt_for_new_passphrase()

    Keychain.set_master_passphrase(current_passphrase=None, new_passphrase=passphrase, save_passphrase=save_passphrase)


def set_or_update_passphrase(passphrase: Optional[str], current_passphrase: Optional[str], hint: Optional[str]) -> bool:
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

    success: bool = False
    new_passphrase: Optional[str] = passphrase
    save_passphrase: bool = False

    try:
        # Prompt for the new passphrase, if necessary
        if new_passphrase is None:
            new_passphrase, save_passphrase = prompt_for_new_passphrase()

        if new_passphrase == current_passphrase:
            raise ValueError("passphrase is unchanged")

        Keychain.set_master_passphrase(
            current_passphrase=current_passphrase,
            new_passphrase=new_passphrase,
            passphrase_hint=hint,
            save_passphrase=save_passphrase,
        )
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
            raise

    return current_passphrase


def default_passphrase() -> str:
    return DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE


def using_default_passphrase() -> bool:
    if not Keychain.has_master_passphrase():
        return False

    return Keychain.master_passphrase_is_valid(default_passphrase())


def display_passphrase_hint() -> None:
    passphrase_hint = Keychain.get_master_passphrase_hint()
    if passphrase_hint is not None:
        print(f"Passphrase hint: {passphrase_hint}")  # lgtm [py/clear-text-logging-sensitive-data]
    else:
        print("Passphrase hint is not set")


def update_passphrase_hint(hint: Optional[str] = None) -> bool:
    updated: bool = False
    if Keychain.has_master_passphrase() is False or using_default_passphrase():
        print("Updating the passphrase hint requires that a passphrase has been set")
    else:
        current_passphrase: Optional[str] = get_current_passphrase()
        if current_passphrase is None:
            print("Keyring is not passphrase-protected")
        else:
            # Set or remove the passphrase hint
            Keychain.set_master_passphrase_hint(current_passphrase, hint)
            updated = True

    return updated


def set_passphrase_hint(hint: str) -> None:
    if update_passphrase_hint(hint):
        print("Passphrase hint set")
    else:
        print("Passphrase hint was not updated")


def remove_passphrase_hint() -> None:
    if update_passphrase_hint(None):
        print("Passphrase hint removed")
    else:
        print("Passphrase hint was not removed")


async def async_update_daemon_passphrase_cache_if_running(root_path: Path, config: Dict[str, Any]) -> None:
    """
    Attempt to connect to the daemon and update the cached passphrase
    """
    new_passphrase = Keychain.get_cached_master_passphrase()
    assert new_passphrase is not None

    try:
        async with acquire_connection_to_daemon(root_path, config, quiet=True) as daemon:
            if daemon is not None:
                response = await daemon.unlock_keyring(new_passphrase)
                if response is None:
                    raise Exception("daemon didn't respond")

                success: bool = response.get("data", {}).get("success", False)
                if success is False:
                    error = response.get("data", {}).get("error", "unknown error")
                    raise Exception(error)
    except Exception as e:
        print(f"Failed to notify daemon of updated keyring passphrase: {e}")
