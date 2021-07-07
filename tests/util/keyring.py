import os
import tempfile

from chia.util.file_keyring import FileKeyring
from chia.util.keychain import Keychain
from chia.util.keyring_wrapper import KeyringWrapper
from functools import wraps
from keyring.util import platform_
from keyrings.cryptfile.cryptfile import CryptFileKeyring  # pyright: reportMissingImports=false
from pathlib import Path
from typing import Optional
from unittest.mock import patch


def create_empty_cryptfilekeyring():
    """
    Create an empty legacy keyring
    """
    crypt_file_keyring = CryptFileKeyring()
    fd = os.open(crypt_file_keyring.file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    os.close(fd)
    assert Path(crypt_file_keyring.file_path).exists()


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
            with TempKeyring(populate=populate):
                # Create an empty legacy keyring
                create_empty_cryptfilekeyring()
                return method(self, *args, **kwargs)

        return inner

    return outer


class TempKeyring:
    def __init__(
        self,
        user: str = "testing-1.8.0",
        testing: bool = True,
        populate: bool = False,
        existing_keyring_path: str = None,
        delete_on_cleanup: bool = True,
    ):
        self.keychain = self._patch_and_create_keychain(user, testing, populate, existing_keyring_path)
        self.delete_on_cleanup = delete_on_cleanup
        self.cleaned_up = False

    def _patch_and_create_keychain(
        self, user: str, testing: bool, populate: bool, existing_keyring_path: Optional[str]
    ):
        existing_keyring_dir = Path(existing_keyring_path).parent if existing_keyring_path else None
        temp_dir = existing_keyring_dir or tempfile.mkdtemp(prefix="test_keyring_wrapper")

        mock_supports_keyring_passphrase_patch = patch("chia.util.keychain.supports_keyring_passphrase")
        mock_supports_keyring_passphrase = mock_supports_keyring_passphrase_patch.start()

        # Patch supports_keyring_passphrase() to return True
        mock_supports_keyring_passphrase.return_value = True

        mock_configure_backend_patch = patch.object(KeyringWrapper, "_configure_backend")
        mock_configure_backend = mock_configure_backend_patch.start()
        setup_mock_file_keyring(mock_configure_backend, temp_dir, populate=populate)

        mock_data_root_patch = patch.object(platform_, "data_root")
        mock_data_root = mock_data_root_patch.start()

        # Mock CryptFileKeyring's file_path indirectly by changing keyring.util.platform_.data_root
        # We don't want CryptFileKeyring finding the real legacy keyring
        mock_data_root.return_value = temp_dir

        keychain = Keychain(user=user, testing=testing)

        # Stash the temp_dir in the keychain instance
        keychain._temp_dir = temp_dir  # type: ignore

        # Stash the patches in the keychain instance
        keychain._mock_supports_keyring_passphrase_patch = mock_supports_keyring_passphrase_patch  # type: ignore
        keychain._mock_configure_backend_patch = mock_configure_backend_patch  # type: ignore
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
            temp_dir = self.keychain._temp_dir
            print(f"Cleaning up temp keychain in dir: {temp_dir}")
            tempfile.TemporaryDirectory._rmtree(temp_dir)

        self.keychain._mock_supports_keyring_passphrase_patch.stop()
        self.keychain._mock_configure_backend_patch.stop()
        self.keychain._mock_data_root_patch.stop()

        self.cleaned_up = True
