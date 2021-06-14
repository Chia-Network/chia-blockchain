import logging
import os
import tempfile

from chia.util.file_keyring import FileKeyring
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
        os.makedirs(os.path.dirname(file_keyring_path), 0o775, False)
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
    mock_configure_backend.return_value = FileKeyring(root_path=Path(temp_file_keyring_dir))


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
        @patch.object(KeyringWrapper, "_configure_backend")
        @patch.object(platform_, "data_root")
        @using_temp_keyring_dir
        def inner(self, mock_data_root, mock_configure_backend, temp_file_keyring_dir, *args, **kwargs):
            setup_mock_file_keyring(mock_configure_backend, temp_file_keyring_dir, populate=populate)

            # Mock CryptFileKeyring's file_path indirectly by changing keyring.util.platform_.data_root
            # We don't want CryptFileKeyring finding the real legacy keyring
            mock_data_root.return_value = temp_file_keyring_dir

            func(self, *args, **kwargs)

        return inner

    return outer


def using_temp_file_keyring_and_cryptfilekeyring(populate=False):
    def outer(func):
        @patch.object(KeyringWrapper, "_configure_backend")
        @patch.object(platform_, "data_root")
        @using_temp_keyring_dir
        def inner(self, mock_data_root, mock_configure_backend, temp_file_keyring_dir, *args, **kwargs):
            setup_mock_file_keyring(mock_configure_backend, temp_file_keyring_dir)

            # Mock CryptFileKeyring's file_path indirectly by changing keyring.util.platform_.data_root
            mock_data_root.return_value = temp_file_keyring_dir

            # Create an empty legacy keyring
            create_empty_cryptfilekeyring()

            func(self, *args, **kwargs)

        return inner

    return outer
