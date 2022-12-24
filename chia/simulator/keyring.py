from __future__ import annotations

import os
import shutil
import tempfile
from functools import wraps
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from chia.util.file_keyring import FileKeyring, keyring_path_from_root
from chia.util.keychain import Keychain
from chia.util.keyring_wrapper import KeyringWrapper


def setup_mock_file_keyring(mock_configure_backend, temp_file_keyring_dir, populate=False):
    if populate:
        # Populate the file keyring with an empty (but encrypted) data set
        file_keyring_path = keyring_path_from_root(Path(temp_file_keyring_dir))
        os.makedirs(os.path.dirname(file_keyring_path), 0o700, True)
        with open(
            os.open(
                keyring_path_from_root(Path(temp_file_keyring_dir)),
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
    mock_configure_backend.return_value = FileKeyring.create(keys_root_path=Path(temp_file_keyring_dir))


def using_temp_file_keyring(populate: bool = False):
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


class TempKeyring:
    def __init__(
        self,
        *,
        user: str = "testing-1.8.0",
        service: str = "testing-chia-1.8.0",
        populate: bool = False,
        existing_keyring_path: Optional[str] = None,
        delete_on_cleanup: bool = True,
        use_os_credential_store: bool = False,
    ):
        self.keychain = self._patch_and_create_keychain(
            user=user,
            service=service,
            populate=populate,
            existing_keyring_path=existing_keyring_path,
            use_os_credential_store=use_os_credential_store,
        )
        self.old_keys_root_path = None
        self.delete_on_cleanup = delete_on_cleanup
        self.cleaned_up = False

    def _patch_and_create_keychain(
        self,
        *,
        user: str,
        service: str,
        populate: bool,
        existing_keyring_path: Optional[str],
        use_os_credential_store: bool,
    ):
        existing_keyring_dir = Path(existing_keyring_path).parent if existing_keyring_path else None
        temp_dir = existing_keyring_dir or tempfile.mkdtemp(prefix="test_keyring_wrapper")

        mock_supports_os_passphrase_storage_patch = patch("chia.util.keychain.supports_os_passphrase_storage")
        mock_supports_os_passphrase_storage = mock_supports_os_passphrase_storage_patch.start()

        # Patch supports_os_passphrase_storage() to return use_os_credential_store
        mock_supports_os_passphrase_storage.return_value = use_os_credential_store

        mock_configure_backend_patch = patch.object(KeyringWrapper, "_configure_backend")
        mock_configure_backend = mock_configure_backend_patch.start()
        setup_mock_file_keyring(mock_configure_backend, temp_dir, populate=populate)

        keychain = Keychain(user=user, service=service)
        keychain.keyring_wrapper = KeyringWrapper(keys_root_path=Path(temp_dir))

        # Stash the temp_dir in the keychain instance
        keychain._temp_dir = temp_dir  # type: ignore

        # Stash the patches in the keychain instance
        keychain._mock_supports_os_passphrase_storage_patch = mock_supports_os_passphrase_storage_patch  # type: ignore
        keychain._mock_configure_backend_patch = mock_configure_backend_patch  # type: ignore

        return keychain

    def __enter__(self):
        assert not self.cleaned_up
        if KeyringWrapper.get_shared_instance(create_if_necessary=False) is not None:
            self.old_keys_root_path = KeyringWrapper.get_shared_instance().keys_root_path
            KeyringWrapper.cleanup_shared_instance()
        kc = self.get_keychain()
        KeyringWrapper.set_keys_root_path(kc.keyring_wrapper.keys_root_path)
        return kc

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.cleanup()

    def get_keychain(self) -> Keychain:
        return self.keychain

    def cleanup(self) -> None:
        assert not self.cleaned_up

        keys_root_path = self.keychain.keyring_wrapper.keys_root_path

        if self.delete_on_cleanup:
            self.keychain.keyring_wrapper.keyring.cleanup_keyring_file_watcher()
            shutil.rmtree(self.keychain._temp_dir)

        if self.old_keys_root_path is not None:
            if KeyringWrapper.get_shared_instance(create_if_necessary=False) is not None:
                shared_keys_root_path = KeyringWrapper.get_shared_instance().keys_root_path
                if shared_keys_root_path == keys_root_path:
                    KeyringWrapper.cleanup_shared_instance()
                    KeyringWrapper.set_keys_root_path(self.old_keys_root_path)
                    KeyringWrapper.get_shared_instance()

        self.cleaned_up = True
