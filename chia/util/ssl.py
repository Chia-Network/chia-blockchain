import stat
import sys
from chia.util.config import load_config, traverse_dict
from chia.util.permissions import octal_mode_string, verify_file_permissions
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DEFAULT_PERMISSIONS_CERT_FILE: int = 0o644
DEFAULT_PERMISSIONS_KEY_FILE: int = 0o600

# Masks containing permission bits we don't allow
RESTRICT_MASK_CERT_FILE: int = stat.S_IWGRP | stat.S_IXGRP | stat.S_IWOTH | stat.S_IXOTH  # 0o033
RESTRICT_MASK_KEY_FILE: int = (
    stat.S_IRGRP | stat.S_IWGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH
)  # 0o077


class SSLInvalidPermissions(Exception):
    def __init__(self, files: List[Tuple[Path, int]]):
        msg = "One or more file permissions are too open:\n"
        for (file, mode) in files:
            msg += f"\t{file} (permissions = {octal_mode_string(mode)})\n"
        msg += f"Expected permissions are {octal_mode_string(DEFAULT_PERMISSIONS_CERT_FILE)} "
        msg += f"for crt files and {octal_mode_string(DEFAULT_PERMISSIONS_KEY_FILE)} for key files"
        super().__init__(msg)

    pass


def print_ssl_perm_warning(path: Path, actual_mode: int, expected_mode: int, show_banner: bool = True):
    if show_banner:
        print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
        print("@             WARNING: UNPROTECTED SSL FILE!              @")
        print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
    print(
        f"Permissions {octal_mode_string(actual_mode)} for '{path}' are too open. "
        f"Expected {octal_mode_string(expected_mode)}"
    )


def verify_ssl_certs_and_keys(
    cert_and_key_paths: List[Tuple[Optional[Path], Optional[Path]]]
) -> List[Tuple[Path, int]]:
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
                    cert_path, cert_actual_mode, DEFAULT_PERMISSIONS_CERT_FILE, show_banner=not banner_shown
                )
                banner_shown = True
                invalid_files_and_modes.append((cert_path, cert_actual_mode))

        if key_path is not None:
            key_perms_valid, key_actual_mode = verify_file_permissions(key_path, RESTRICT_MASK_KEY_FILE)
            if not key_perms_valid:
                print_ssl_perm_warning(
                    key_path, key_actual_mode, DEFAULT_PERMISSIONS_KEY_FILE, show_banner=not banner_shown
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

    config: Dict = load_config(root_path, "config.yaml")
    cert_config_key_paths = [
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
    key_config_key_paths = [
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

    valid: bool = True
    banner_shown: bool = False

    for (key_paths, mask, expected_mode) in [
        (cert_config_key_paths, RESTRICT_MASK_CERT_FILE, DEFAULT_PERMISSIONS_CERT_FILE),
        (key_config_key_paths, RESTRICT_MASK_KEY_FILE, DEFAULT_PERMISSIONS_KEY_FILE),
    ]:
        for key_path in key_paths:
            try:
                file = root_path / Path(traverse_dict(config, key_path))
                # Check that the file permissions are not too permissive
                (good_perms, mode) = verify_file_permissions(file, mask)
                if not good_perms:
                    print_ssl_perm_warning(file, mode, expected_mode, show_banner=not banner_shown)
                    banner_shown = True
                    valid = False
            except Exception as e:
                print(f"Unable to check permissions for {key_path}: {e}")

    mozilla_root_ca = get_mozilla_ca_crt()
    (good_perms, mode) = verify_file_permissions(Path(mozilla_root_ca), RESTRICT_MASK_CERT_FILE)
    if not good_perms:
        print_ssl_perm_warning(file, mode, expected_mode, show_banner=not banner_shown)
        banner_shown = True
        valid = False

    if not valid:
        print("Please fix your file permissions and try again.")
        sys.exit(1)
