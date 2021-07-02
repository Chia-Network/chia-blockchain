import logging
import os
import tempfile

from chia.util.file_keyring import FileKeyring
from chia.util.keychain import Keychain
from chia.util.keyring_wrapper import KeyringWrapper
from keyring.util import platform_
from keyrings.cryptfile.cryptfile import CryptFileKeyring  # pyright: reportMissingImports=false
from pathlib import Path
from unittest.mock import patch


log = logging.getLogger(__name__)


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
                # Encrypted using DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD. Data holds an empty keyring.
                "data: Re+on6HbYfUm58bGVEfPoOwI+y2GrR1QUByZ8Qq8AgFnKc9tMnkk3ss=\n"
                "nonce: 41a01a265e74ad324b24cbe0\n"
                "salt: e1ca9b308dee7968e22a05bde98df3eb\n"
                "version: 1"
            )

    # Create the file keyring
    mock_configure_backend.return_value = FileKeyring(keys_root_path=Path(temp_file_keyring_dir))


def using_temp_keyring_dir(func):
    """
    Decorator that will create a temporary keyring directory that is automatically
    cleaned-up after invoking the decorated function
    """

    def inner(*args, **kwargs):
        with tempfile.TemporaryDirectory(prefix="test_keyring_wrapper") as temp_file_keyring_dir:
            log.warning(f"[pid:{os.getpid()}] using temp keyring dir: {temp_file_keyring_dir}")
            func(*args, **dict(kwargs, temp_file_keyring_dir=temp_file_keyring_dir))

    return inner


def using_temp_file_keyring(populate=False):
    def outer(func):
        @patch("chia.util.keychain.supports_keyring_password")
        @patch.object(KeyringWrapper, "_configure_backend")
        @patch.object(platform_, "data_root")
        @using_temp_keyring_dir
        def inner(
            self,
            mock_data_root,
            mock_configure_backend,
            mock_supports_keyring_password,
            temp_file_keyring_dir,
            *args,
            **kwargs,
        ):
            # Patch supports_keyring_password() to return True
            mock_supports_keyring_password.return_value = True

            setup_mock_file_keyring(mock_configure_backend, temp_file_keyring_dir, populate=populate)

            # Mock CryptFileKeyring's file_path indirectly by changing keyring.util.platform_.data_root
            # We don't want CryptFileKeyring finding the real legacy keyring
            mock_data_root.return_value = temp_file_keyring_dir

            func(self, *args, **kwargs)

        return inner

    return outer


def using_temp_file_keyring_and_cryptfilekeyring(populate=False):
    def outer(func):
        @patch("chia.util.keychain.supports_keyring_password")
        @patch.object(KeyringWrapper, "_configure_backend")
        @patch.object(platform_, "data_root")
        @using_temp_keyring_dir
        def inner(
            self,
            mock_data_root,
            mock_configure_backend,
            mock_supports_keyring_password,
            temp_file_keyring_dir,
            *args,
            **kwargs,
        ):
            # Patch supports_keyring_password() to return True
            mock_supports_keyring_password.return_value = True

            setup_mock_file_keyring(mock_configure_backend, temp_file_keyring_dir)

            # Mock CryptFileKeyring's file_path indirectly by changing keyring.util.platform_.data_root
            mock_data_root.return_value = temp_file_keyring_dir

            # Create an empty legacy keyring
            create_empty_cryptfilekeyring()

            func(self, *args, **kwargs)

        return inner

    return outer


class TempKeyring:
    def __init__(self, user: str = "testing-1.8.0", testing: bool = True):
        self.keychain = self._patch_and_create_keychain(user, testing)
        self.cleaned_up = False

    def _patch_and_create_keychain(self, user: str, testing: bool):
        temp_dir = tempfile.mkdtemp(prefix="test_keyring_wrapper")

        mock_supports_keyring_password_patch = patch("chia.util.keychain.supports_keyring_password")
        mock_supports_keyring_password = mock_supports_keyring_password_patch.start()

        # Patch supports_keyring_password() to return True
        mock_supports_keyring_password.return_value = True

        mock_configure_backend_patch = patch.object(KeyringWrapper, "_configure_backend")
        mock_configure_backend = mock_configure_backend_patch.start()
        setup_mock_file_keyring(mock_configure_backend, temp_dir, populate=False)

        mock_data_root_patch = patch.object(platform_, "data_root")
        mock_data_root = mock_data_root_patch.start()

        # Mock CryptFileKeyring's file_path indirectly by changing keyring.util.platform_.data_root
        # We don't want CryptFileKeyring finding the real legacy keyring
        mock_data_root.return_value = temp_dir

        keychain = Keychain(user=user, testing=testing)

        # Stash the temp_dir in the keychain instance
        keychain._temp_dir = temp_dir  # type: ignore

        # Stash the patches in the keychain instance
        keychain._mock_supports_keyring_password_patch = mock_supports_keyring_password_patch  # type: ignore
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

        temp_dir = self.keychain._temp_dir
        print(f"Cleaning up temp keychain in dir: {temp_dir}")
        tempfile.TemporaryDirectory._rmtree(temp_dir)

        self.keychain._mock_supports_keyring_password_patch.stop()
        self.keychain._mock_configure_backend_patch.stop()
        self.keychain._mock_data_root_patch.stop()

        self.cleaned_up = True
