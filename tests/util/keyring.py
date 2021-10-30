import os
import shutil
import tempfile

from chia.util.file_keyring import FileKeyring
from chia.util.keychain import Keychain, default_keychain_service, default_keychain_user, get_private_key_user
from chia.util.keyring_wrapper import KeyringWrapper
from functools import wraps
from keyring.util import platform_
from keyrings.cryptfile.cryptfile import CryptFileKeyring  # pyright: reportMissingImports=false
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch


def create_empty_cryptfilekeyring() -> CryptFileKeyring:
    """
    Create an empty legacy keyring
    """
    crypt_file_keyring = CryptFileKeyring()
    fd = os.open(crypt_file_keyring.file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.close(fd)
    assert Path(crypt_file_keyring.file_path).exists()
    return crypt_file_keyring


def add_dummy_key_to_cryptfilekeyring(crypt_file_keyring: CryptFileKeyring):
    """
    Add a fake key to the CryptFileKeyring
    """
    crypt_file_keyring.keyring_key = "your keyring password"  # type: ignore
    user: str = get_private_key_user(default_keychain_user(), 0)
    crypt_file_keyring.set_password(default_keychain_service(), user, "abc123")


def setup_mock_file_keyring(mock_configure_backend, temp_file_keyring_dir, populate=False):
    if populate:
        # Populate the file keyring with an empty (but encrypted) data set
        file_keyring_path = FileKeyring.keyring_path_from_root(Path(temp_file_keyring_dir))
        os.makedirs(os.path.dirname(file_keyring_path), 0o700, True)
        with open(
            os.open(
                FileKeyring.keyring_path_from_root(Path(temp_file_keyring_dir)),
                os.O_CREAT | os.O_WRONLY | os.O_TRUNC,
                0o600,
            ),
            "w",
        ) as f:
            f.write(
                # Encrypted using DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE. Data holds an empty keyring.
                "data: xtcxYOWtbeO9ruv4Nkwhw1pcTJCNh/fvPSdFxez/L0ysnag=\n"
                "nonce: 17ecac58deb7a392fccef49e\n"
                "salt: b1aa32d5730288d653e82017e4a4057c\n"
                "version: 1"
            )

    # Create the file keyring
    mock_configure_backend.return_value = FileKeyring(keys_root_path=Path(temp_file_keyring_dir))


def using_temp_file_keyring(populate=False):
    """
    Decorator that will create a temporary directory with a temporary keyring that is
    automatically cleaned-up after invoking the decorated function. If `populate` is
    true, the newly created keyring will be populated with a payload containing 0 keys
    using the default passphrase.
    """

    def outer(method):
        @wraps(method)
        def inner(self, *args, **kwargs):
            with TempKeyring(populate=populate):
                return method(self, *args, **kwargs)

        return inner

    return outer


def using_temp_file_keyring_and_cryptfilekeyring(populate=False):
    """
    Like the `using_temp_file_keyring` decorator, this decorator will create a temp
    dir and temp keyring. Additionally, an empty legacy Cryptfile keyring will be
    created in the temp directory.
    """

    def outer(method):
        @wraps(method)
        def inner(self, *args, **kwargs):
            with TempKeyring(populate=populate, setup_cryptfilekeyring=True):
                return method(self, *args, **kwargs)

        return inner

    return outer


class TempKeyring:
    def __init__(
        self,
        *,
        user: str = "testing-1.8.0",
        service: str = "testing-chia-1.8.0",
        populate: bool = False,
        setup_cryptfilekeyring: bool = False,
        existing_keyring_path: str = None,
        delete_on_cleanup: bool = True,
        use_os_credential_store: bool = False,
    ):
        self.keychain = self._patch_and_create_keychain(
            user=user,
            service=service,
            populate=populate,
            existing_keyring_path=existing_keyring_path,
            use_os_credential_store=use_os_credential_store,
            setup_cryptfilekeyring=setup_cryptfilekeyring,
        )
        self.delete_on_cleanup = delete_on_cleanup
        self.cleaned_up = False

    def _patch_and_create_keychain(
        self,
        *,
        user: str,
        service: str,
        populate: bool,
        setup_cryptfilekeyring: bool,
        existing_keyring_path: Optional[str],
        use_os_credential_store: bool,
    ):
        existing_keyring_dir = Path(existing_keyring_path).parent if existing_keyring_path else None
        temp_dir = existing_keyring_dir or tempfile.mkdtemp(prefix="test_keyring_wrapper")

        mock_supports_keyring_passphrase_patch = patch("chia.util.keychain.supports_keyring_passphrase")
        mock_supports_keyring_passphrase = mock_supports_keyring_passphrase_patch.start()

        # Patch supports_keyring_passphrase() to return True
        mock_supports_keyring_passphrase.return_value = True

        mock_supports_os_passphrase_storage_patch = patch("chia.util.keychain.supports_os_passphrase_storage")
        mock_supports_os_passphrase_storage = mock_supports_os_passphrase_storage_patch.start()

        # Patch supports_os_passphrase_storage() to return use_os_credential_store
        mock_supports_os_passphrase_storage.return_value = use_os_credential_store

        mock_configure_backend_patch = patch.object(KeyringWrapper, "_configure_backend")
        mock_configure_backend = mock_configure_backend_patch.start()
        setup_mock_file_keyring(mock_configure_backend, temp_dir, populate=populate)

        mock_configure_legacy_backend_patch: Any = None
        if setup_cryptfilekeyring is False:
            mock_configure_legacy_backend_patch = patch.object(KeyringWrapper, "_configure_legacy_backend")
            mock_configure_legacy_backend = mock_configure_legacy_backend_patch.start()
            mock_configure_legacy_backend.return_value = None

        mock_data_root_patch = patch.object(platform_, "data_root")
        mock_data_root = mock_data_root_patch.start()

        # Mock CryptFileKeyring's file_path indirectly by changing keyring.util.platform_.data_root
        # We don't want CryptFileKeyring finding the real legacy keyring
        mock_data_root.return_value = temp_dir

        if setup_cryptfilekeyring is True:
            crypt_file_keyring = create_empty_cryptfilekeyring()
            add_dummy_key_to_cryptfilekeyring(crypt_file_keyring)

        keychain = Keychain(user=user, service=service)
        keychain.keyring_wrapper = KeyringWrapper(keys_root_path=Path(temp_dir))

        # Stash the temp_dir in the keychain instance
        keychain._temp_dir = temp_dir  # type: ignore

        # Stash the patches in the keychain instance
        keychain._mock_supports_keyring_passphrase_patch = mock_supports_keyring_passphrase_patch  # type: ignore
        keychain._mock_supports_os_passphrase_storage_patch = mock_supports_os_passphrase_storage_patch  # type: ignore
        keychain._mock_configure_backend_patch = mock_configure_backend_patch  # type: ignore
        keychain._mock_configure_legacy_backend_patch = mock_configure_legacy_backend_patch  # type: ignore
        keychain._mock_data_root_patch = mock_data_root_patch  # type: ignore

        return keychain

    def __enter__(self):
        assert not self.cleaned_up
        return self.get_keychain()

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.cleanup()

    def get_keychain(self):
        return self.keychain

    def cleanup(self):
        assert not self.cleaned_up

        if self.delete_on_cleanup:
            self.keychain.keyring_wrapper.keyring.cleanup_keyring_file_watcher()
            temp_dir = self.keychain._temp_dir
            print(f"Cleaning up temp keychain in dir: {temp_dir}")
            shutil.rmtree(temp_dir)

        self.keychain._mock_supports_keyring_passphrase_patch.stop()
        self.keychain._mock_supports_os_passphrase_storage_patch.stop()
        self.keychain._mock_configure_backend_patch.stop()
        if self.keychain._mock_configure_legacy_backend_patch is not None:
            self.keychain._mock_configure_legacy_backend_patch.stop()
        self.keychain._mock_data_root_patch.stop()

        self.cleaned_up = True
