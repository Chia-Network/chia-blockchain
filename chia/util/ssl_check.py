from __future__ import annotations

import os
import stat
import sys
from logging import Logger
from pathlib import Path
from typing import List, Optional, Set, Tuple

from chia.util.config import load_config, traverse_dict
from chia.util.permissions import octal_mode_string, verify_file_permissions

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
    "data_layer:ssl:private_crt",
    "data_layer:ssl:public_crt",
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


def get_all_ssl_file_paths(root_path: Path) -> Tuple[List[Path], List[Path]]:
    """Lookup config values and append to a list of files whose permissions we need to check"""
    from chia.ssl.create_ssl import get_mozilla_ca_crt

    all_certs: List[Path] = []
    all_keys: List[Path] = []

    try:
        config = load_config(root_path, "config.yaml", exit_on_error=False, fill_missing_services=True)
        for paths, parsed_list in [(CERT_CONFIG_KEY_PATHS, all_certs), (KEY_CONFIG_KEY_PATHS, all_keys)]:
            for path in paths:
                try:
                    file = root_path / Path(traverse_dict(config, path))
                    parsed_list.append(file)
                except Exception as e:
                    print(
                        f"Failed to lookup config value for {path}: {e}"
                    )  # lgtm [py/clear-text-logging-sensitive-data]

        # Check the Mozilla Root CAs as well
        all_certs.append(Path(get_mozilla_ca_crt()))
    except (FileNotFoundError, ValueError):
        pass

    return all_certs, all_keys


def get_ssl_perm_warning(path: Path, actual_mode: int, expected_mode: int) -> str:
    return (
        f"Permissions {octal_mode_string(actual_mode)} for "
        f"'{path}' are too open. "  # lgtm [py/clear-text-logging-sensitive-data]
        f"Expected {octal_mode_string(expected_mode)}"
    )


def verify_ssl_certs_and_keys(
    cert_paths: List[Path], key_paths: List[Path], log: Optional[Logger] = None
) -> List[Tuple[Path, int, int]]:
    """Check that file permissions are properly set for the provided SSL cert and key files"""
    if sys.platform == "win32" or sys.platform == "cygwin":
        # TODO: ACLs for SSL certs/keys on Windows
        return []

    invalid_files_and_modes: List[Tuple[Path, int, int]] = []

    def verify_paths(paths: List[Path], restrict_mask: int, expected_permissions: int) -> None:
        nonlocal invalid_files_and_modes
        for path in paths:
            try:
                # Check that the file permissions are not too permissive
                is_valid, actual_permissions = verify_file_permissions(path, restrict_mask)
                if not is_valid:
                    if log is not None:
                        log.error(get_ssl_perm_warning(path, actual_permissions, expected_permissions))
                    warned_ssl_files.add(path)
                    invalid_files_and_modes.append((path, actual_permissions, expected_permissions))
            except FileNotFoundError:
                # permissions can't be dangerously wrong on nonexistent files
                pass
            except Exception as e:
                print(f"Unable to check permissions for {path}: {e}")  # lgtm [py/clear-text-logging-sensitive-data]

    verify_paths(cert_paths, RESTRICT_MASK_CERT_FILE, DEFAULT_PERMISSIONS_CERT_FILE)
    verify_paths(key_paths, RESTRICT_MASK_KEY_FILE, DEFAULT_PERMISSIONS_KEY_FILE)

    return invalid_files_and_modes


def check_ssl(root_path: Path) -> None:
    """
    Sanity checks on the SSL configuration. Checks that file permissions are properly
    set on the keys and certs, warning and exiting if permissions are incorrect.
    """
    if sys.platform == "win32" or sys.platform == "cygwin":
        # TODO: ACLs for SSL certs/keys on Windows
        return None

    certs_to_check, keys_to_check = get_all_ssl_file_paths(root_path)
    invalid_files = verify_ssl_certs_and_keys(certs_to_check, keys_to_check)
    if len(invalid_files):
        lines = [
            "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
            "@             WARNING: UNPROTECTED SSL FILE!              @",
            "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@",
            *(
                get_ssl_perm_warning(path, actual_permissions, expected_permissions)
                for path, actual_permissions, expected_permissions in invalid_files
            ),
            "One or more SSL files were found with permission issues.",
            "Run the following to fix issues: chia init --fix-ssl-permissions",
        ]
        print("\n".join(lines), file=sys.stderr)


def check_and_fix_permissions_for_ssl_file(file: Path, mask: int, updated_mode: int) -> Tuple[bool, bool]:
    """Check file permissions and attempt to fix them if found to be too open"""
    if sys.platform == "win32" or sys.platform == "cygwin":
        # TODO: ACLs for SSL certs/keys on Windows
        return True, False

    valid: bool = True
    updated: bool = False

    # Check that the file permissions are not too permissive
    try:
        (good_perms, mode) = verify_file_permissions(file, mask)
        if not good_perms:
            valid = False
            print(
                f"Attempting to set permissions {octal_mode_string(updated_mode)} on "
                f"{file}"  # lgtm [py/clear-text-logging-sensitive-data]
            )
            os.chmod(str(file), updated_mode)
            updated = True
    except Exception as e:
        print(f"Failed to change permissions on {file}: {e}")  # lgtm [py/clear-text-logging-sensitive-data]
        valid = False

    return valid, updated


def fix_ssl(root_path: Path) -> None:
    """Attempts to fix SSL cert/key file permissions that are too open"""

    if sys.platform == "win32" or sys.platform == "cygwin":
        # TODO: ACLs for SSL certs/keys on Windows
        return None

    updated: bool = False
    encountered_error: bool = False

    certs_to_check, keys_to_check = get_all_ssl_file_paths(root_path)
    files_to_fix = verify_ssl_certs_and_keys(certs_to_check, keys_to_check)

    for file, mask, updated_mode in files_to_fix:
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
