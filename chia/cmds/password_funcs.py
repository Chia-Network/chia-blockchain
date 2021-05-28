from chia.util.keychain import Keychain, obtain_current_password
from getpass import getpass
from io import TextIOWrapper
from typing import Optional, Tuple


MIN_PASSWORD_LEN = 8


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
        print(f"\nPasswords must be {MIN_PASSWORD_LEN} characters or longer")
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


def set_or_update_password(password: Optional[str], current_password: Optional[str]) -> None:
    # Prompt for the current password, if necessary
    if Keychain.is_password_protected() and not current_password:
        try:
            current_password = obtain_current_password("Current Password: ")
        except Exception as e:
            print(f"Unable to confirm current password: {e}")

    new_password = password
    try:
        # Prompt for the new password, if necessary
        if not new_password:
            new_password = prompt_for_new_password()

        if new_password == current_password:
            raise ValueError("password is unchanged")

        Keychain.set_password(current_password=current_password, new_password=new_password)
    except Exception as e:
        print(f"Unable to set or update password: {e}")


def remove_password(current_password: Optional[str]) -> None:
    if not Keychain.is_password_protected():
        print("Password is not currently set")
    else:
        # Prompt for the current password, if necessary
        if not current_password:
            try:
                current_password = obtain_current_password("Current Password: ")
            except Exception as e:
                print(f"Unable to confirm current password: {e}")

        try:
            Keychain.remove_password(current_password)
        except Exception as e:
            print(f"Unable to remove password: {e}")


def cache_password(password: str) -> None:
    Keychain.set_cached_password(password)
