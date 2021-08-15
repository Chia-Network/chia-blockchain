import os
import stat
import sys
from chia.util.config import load_config, traverse_dict
from chia.util.permissions import octal_mode_string, verify_file_permissions
from logging import Logger
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

DEFAULT_PERMISSIONS_CERT_FILE: int = 0o644
DEFAULT_PERMISSIONS_KEY_FILE: int = 0o600

# Masks containing permission bits we don't allow
RESTRICT_MASK_CERT_FILE: int = stat.S_IWGRP | stat.S_IXGRP | stat.S_IWOTH | stat.S_IXOTH  # 0o033
RESTRICT_MASK_KEY_FILE: int = (
    stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH
)  # 0o077

CERT_CONFIG_KEY_PATHS = [
    "chia_ssl_ca:crt",
    "daemon_ssl:private_crt",
    "farmer:ssl:private_crt",
    "farmer:ssl:public_crt",
    "full_node:ssl:private_crt",
    "full_node:ssl:public_crt",
    "harvester:chia_ssl_ca:crt",
    "harvester:private_ssl_ca:crt",
    "harvester:ssl:private_crt",
    "introducer:ssl:public_crt",
    "private_ssl_ca:crt",
    "timelord:ssl:private_crt",
    "timelord:ssl:public_crt",
    "ui:daemon_ssl:private_crt",
    "wallet:ssl:private_crt",
    "wallet:ssl:public_crt",
]
KEY_CONFIG_KEY_PATHS = [
    "chia_ssl_ca:key",
    "daemon_ssl:private_key",
    "farmer:ssl:private_key",
    "farmer:ssl:public_key",
    "full_node:ssl:private_key",
    "full_node:ssl:public_key",
    "harvester:chia_ssl_ca:key",
    "harvester:private_ssl_ca:key",
    "harvester:ssl:private_key",
    "introducer:ssl:public_key",
    "private_ssl_ca:key",
    "timelord:ssl:private_key",
    "timelord:ssl:public_key",
    "ui:daemon_ssl:private_key",
    "wallet:ssl:private_key",
    "wallet:ssl:public_key",
]


# Set to keep track of which files we've already warned about
warned_ssl_files: Set[Path] = set()


def print_ssl_perm_warning(
    path: Path, actual_mode: int, expected_mode: int, *, show_banner: bool = True, log: Optional[Logger] = None
) -> None:
    if path not in warned_ssl_files:
        if show_banner and len(warned_ssl_files) == 0:
            print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
            print("@             WARNING: UNPROTECTED SSL FILE!              @")
            print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
        msg = (
            f"Permissions {octal_mode_string(actual_mode)} for "
            f"'{path}' are too open. "  # lgtm [py/clear-text-logging-sensitive-data]
            f"Expected {octal_mode_string(expected_mode)}"
        )
        if log is not None:
            log.error(f"{msg}")
        print(f"{msg}")
        warned_ssl_files.add(path)


def verify_ssl_certs_and_keys(
    cert_and_key_paths: List[Tuple[Optional[Path], Optional[Path]]], log: Optional[Logger] = None
) -> List[Tuple[Path, int]]:
    """Check that file permissions are properly set for the provided SSL cert and key files"""
    if sys.platform == "win32" or sys.platform == "cygwin":
        # TODO: ACLs for SSL certs/keys on Windows
        return []

    invalid_files_and_modes: List[Tuple[Path, int]] = []
    banner_shown: bool = False

    for (cert_path, key_path) in cert_and_key_paths:
        if cert_path is not None:
            cert_perms_valid, cert_actual_mode = verify_file_permissions(cert_path, RESTRICT_MASK_CERT_FILE)
            if not cert_perms_valid:
                print_ssl_perm_warning(
                    cert_path, cert_actual_mode, DEFAULT_PERMISSIONS_CERT_FILE, show_banner=not banner_shown, log=log
                )
                banner_shown = True
                invalid_files_and_modes.append((cert_path, cert_actual_mode))

        if key_path is not None:
            key_perms_valid, key_actual_mode = verify_file_permissions(key_path, RESTRICT_MASK_KEY_FILE)
            if not key_perms_valid:
                print_ssl_perm_warning(
                    key_path, key_actual_mode, DEFAULT_PERMISSIONS_KEY_FILE, show_banner=not banner_shown, log=log
                )
                banner_shown = True
                invalid_files_and_modes.append((key_path, key_actual_mode))

    return invalid_files_and_modes


def check_ssl(root_path: Path) -> None:
    """
    Sanity checks on the SSL configuration. Checks that file permissions are properly
    set on the keys and certs, warning and exiting if permissions are incorrect.
    """
    from chia.ssl.create_ssl import get_mozilla_ca_crt

    if sys.platform == "win32" or sys.platform == "cygwin":
        # TODO: ACLs for SSL certs/keys on Windows
        return None

    config: Dict = load_config(root_path, "config.yaml")
    files_to_check: List[Tuple[Path, int, int]] = []
    valid: bool = True
    banner_shown: bool = False

    # Lookup config values and append to a list of files whose permissions we need to check
    for (key_paths, mask, expected_mode) in [
        (CERT_CONFIG_KEY_PATHS, RESTRICT_MASK_CERT_FILE, DEFAULT_PERMISSIONS_CERT_FILE),
        (KEY_CONFIG_KEY_PATHS, RESTRICT_MASK_KEY_FILE, DEFAULT_PERMISSIONS_KEY_FILE),
    ]:
        for key_path in key_paths:
            try:
                file = root_path / Path(traverse_dict(config, key_path))
                files_to_check.append((file, mask, expected_mode))
            except Exception as e:
                print(
                    f"Failed to lookup config value for {key_path}: {e}"  # lgtm [py/clear-text-logging-sensitive-data]
                )

    # Check the Mozilla Root CAs as well
    mozilla_root_ca = get_mozilla_ca_crt()
    files_to_check.append((Path(mozilla_root_ca), RESTRICT_MASK_CERT_FILE, DEFAULT_PERMISSIONS_CERT_FILE))

    for (file, mask, expected_mode) in files_to_check:
        try:
            # Check that the file permissions are not too permissive
            (good_perms, mode) = verify_file_permissions(file, mask)
            if not good_perms:
                print_ssl_perm_warning(file, mode, expected_mode, show_banner=not banner_shown)
                banner_shown = True
                valid = False
        except Exception as e:
            print(f"Unable to check permissions for {key_path}: {e}")  # lgtm [py/clear-text-logging-sensitive-data]

    if not valid:
        print("One or more SSL files were found with permission issues.")
        print("Run `chia init --fix-ssl-permissions` to fix issues.")


def check_and_fix_permissions_for_ssl_file(file: Path, mask: int, updated_mode: int) -> Tuple[bool, bool]:
    """Check file permissions and attempt to fix them if found to be too open"""
    if sys.platform == "win32" or sys.platform == "cygwin":
        # TODO: ACLs for SSL certs/keys on Windows
        return (True, False)

    valid: bool = True
    updated: bool = False

    # Check that the file permissions are not too permissive
    try:
        (good_perms, mode) = verify_file_permissions(file, mask)
        if not good_perms:
            valid = False
            print(
                f"Attempting to set permissions {octal_mode_string(mode)} on "
                f"{file}"  # lgtm [py/clear-text-logging-sensitive-data]
            )
            os.chmod(str(file), updated_mode)
            updated = True
    except Exception as e:
        print(f"Failed to change permissions on {file}: {e}")  # lgtm [py/clear-text-logging-sensitive-data]
        valid = False

    return (valid, updated)


def fix_ssl(root_path: Path) -> None:
    """Attempts to fix SSL cert/key file permissions that are too open"""
    from chia.ssl.create_ssl import get_mozilla_ca_crt

    if sys.platform == "win32" or sys.platform == "cygwin":
        # TODO: ACLs for SSL certs/keys on Windows
        return None

    config: Dict = load_config(root_path, "config.yaml")
    files_to_fix: List[Tuple[Path, int, int]] = []
    updated: bool = False
    encountered_error: bool = False

    for (key_paths, mask, updated_mode) in [
        (CERT_CONFIG_KEY_PATHS, RESTRICT_MASK_CERT_FILE, DEFAULT_PERMISSIONS_CERT_FILE),
        (KEY_CONFIG_KEY_PATHS, RESTRICT_MASK_KEY_FILE, DEFAULT_PERMISSIONS_KEY_FILE),
    ]:
        for key_path in key_paths:
            try:
                file = root_path / Path(traverse_dict(config, key_path))
                files_to_fix.append((file, mask, updated_mode))
            except Exception as e:
                print(
                    f"Failed to lookup config value for {key_path}: {e}"  # lgtm [py/clear-text-logging-sensitive-data]
                )

    # Check the Mozilla Root CAs as well
    mozilla_root_ca = get_mozilla_ca_crt()
    files_to_fix.append((Path(mozilla_root_ca), RESTRICT_MASK_CERT_FILE, DEFAULT_PERMISSIONS_CERT_FILE))

    for (file, mask, updated_mode) in files_to_fix:
        # Check that permissions are correct, and if not, attempt to fix
        (valid, fixed) = check_and_fix_permissions_for_ssl_file(file, mask, updated_mode)
        if fixed:
            updated = True
        if not valid and not fixed:
            encountered_error = True

    if encountered_error:
        print("One or more errors were encountered while updating SSL file permissions...")
    elif updated:
        print("Finished updating SSL file permissions")
    else:
        print("SSL file permissions are correct")
