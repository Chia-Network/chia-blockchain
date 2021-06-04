import keyring as keyring_main

from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.file_keyring import FileKeyring
from keyrings.cryptfile.cryptfile import CryptFileKeyring  # pyright: reportMissingImports=false
from pathlib import Path
from sys import platform
from typing import Optional, Tuple


# We want to protect the keyring, even if a user-specified master password isn't provided
DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD = "$ chia password set # all the cool kids are doing it!"


class KeyringWrapper:
    """
    KeyringWrapper provides an abstraction that the Keychain class can use
    without requiring knowledge of the keyring backend. During initialization,
    a keyring backend is selected based on the OS.

    The wrapper is implemented as a singleton, as it may need to manage state
    related to the master password and handle migration from the legacy
    CryptFileKeyring implementation.
    """
    # Static members
    __shared_instance = None

    # Instance members
    root_path: str = None
    keyring = None
    cached_password: Optional[str] = DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD
    cached_password_is_validated: bool = False
    legacy_keyring = None

    def __init__(self, root_path: str = DEFAULT_ROOT_PATH):
        """
        Initializes the keyring backend based on the OS. For Linux, we previously
        used CryptFileKeyring. We now use our own FileKeyring backend and migrate
        the data from the legacy CryptFileKeyring (on write).
        """
        self.root_path = root_path

        if KeyringWrapper.keyring:
            raise Exception("KeyringWrapper has already been instantiated")

        if platform == "win32" or platform == "cygwin":
            import keyring.backends.Windows

            keyring.set_keyring(keyring.backends.Windows.WinVaultKeyring())
        elif platform == "darwin":
            import keyring.backends.macOS

            keyring.set_keyring(keyring.backends.macOS.Keyring())
        elif platform == "linux":
            # TODO: Leaving this to help debug migration scenarios
            # keyring = CryptFileKeyring()
            # keyring.keyring_key = "your keyring password"  # type: ignore

            keyring = FileKeyring(root_path=self.root_path)
            # If keyring.yaml isn't found or is empty, check if we're using CryptFileKeyring
            if not keyring.has_content():
                old_keyring = CryptFileKeyring()
                if Path(old_keyring.file_path).is_file():
                    print("(TODO: remove) ***** Using legacy keyring")
                    self.legacy_keyring = old_keyring
                    # Legacy keyring is nuked once a master password is set via 'chia password set'
                    self.legacy_keyring.keyring_key = "your keyring password"  # type: ignore
        else:
            keyring = keyring_main

        self.keyring = keyring
        KeyringWrapper.__shared_instance = self

    @staticmethod
    def get_shared_instance():
        if not KeyringWrapper.__shared_instance:
            KeyringWrapper()

        return KeyringWrapper.__shared_instance

    def get_keyring(self):
        """
        Return the current keyring backend. The legacy keyring is preferred if it's in use
        """
        return self.keyring if not self.using_legacy_keyring() else self.legacy_keyring

    def using_legacy_keyring(self) -> bool:
        return self.legacy_keyring is not None

    # Master password support

    def keyring_supports_master_password(self) -> bool:
        return type(self.get_keyring()) in [FileKeyring]

    def get_cached_master_password(self) -> Tuple[Optional[str], bool]:
        """
        Returns a tuple including the currently cached password and a bool
        indicating whether the password has been previously validated.
        """
        return self.cached_password, self.cached_password_is_validated

    def set_cached_master_password(self, password: Optional[str], validated=False) -> None:
        """
        Cache the provided password and optionally indicate whether the password
        has been validated.
        """
        self.cached_password = password
        self.cached_password_is_validated = validated

    def has_cached_master_password(self) -> bool:
        password = self.get_cached_master_password()
        return password is not None and len(password) > 0

    def has_master_password(self) -> bool:
        """
        Returns a bool indicating whether the underlying keyring data
        is secured by a master password.
        """
        return self.keyring_supports_master_password() and self.keyring.has_content()

    def master_password_is_valid(self, password: Optional[str]) -> bool:
        return self.keyring.check_password(password)

    def set_master_password(self, current_password: Optional[str], new_password: str) -> None:
        if self.has_master_password() and not self.master_password_is_valid(current_password):
            raise ValueError("invalid current password")

        self.set_cached_master_password(new_password, validated=True)

        # We'll migrate the legacy contents to the new keyring at this point
        if self.using_legacy_keyring():
            self.migrate_legacy_keyring()
        else:
            # We're reencrypting the keyring contents using the new password. Ensure that the
            # payload has been decrypted by calling load_keyring with the current password.
            self.keyring.load_keyring(password=current_password)
            self.keyring.write_keyring(fresh_salt=True)  # Create a new salt since we're changing the password

    def remove_master_password(self, current_password: Optional[str]) -> None:
        """
        Remove the user-specific master password. We still keep the keyring contents encrypted
        using the default password.
        """
        self.set_master_password(current_password, DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD)

    # Legacy keyring migration
    def migrate_legacy_keyring(self):
        from chia.util.keychain import Keychain

        print("Migrating contents from legacy keyring")
        keychain = Keychain()
        all_private_keys = keychain.get_all_private_keys()
        index = 0
        self.keyring.prepare_for_migration()
        for (private_key, key_bytes) in all_private_keys:
            self.keyring.set_password(
                keychain._get_service(),
                keychain._get_private_key_user(index),
                key_bytes)
            index += 1

        # Stop using the legacy keyring
        # TODO: Delete or clear out the legacy keyring's contents?
        self.legacy_keyring = None

        print("Migration complete")

    # Keyring interface

    def get_password(self, service: str, user: str) -> str:
        # Continue reading from the legacy keyring until we want to write something,
        # at which point we'll migrate the legacy contents to the new keyring
        if self.using_legacy_keyring():
            print("(TODO: remove) ***** get_password is using legacy keyring")
            return self.legacy_keyring.get_password(service, user)

        return self.get_keyring().get_password(service, user)

    def set_password(self, service: str, user: str, password_bytes: bytes):
        # On the first write while using the legacy keyring, we'll start migration
        if self.using_legacy_keyring() and self.has_cached_master_password():
            print("(TODO: remove) ***** set_password called while using legacy keyring: will migrate")
            self.migrate_legacy_keyring()

        self.get_keyring().set_password(service, user, password_bytes)

    def delete_password(self, service: str, user: str):
        # On the first write while using the legacy keyring, we'll start migration
        if self.using_legacy_keyring() and self.has_cached_master_password():
            print("(TODO: remove) ***** delete_password called while using legacy keyring: will migrate")
            self.migrate_legacy_keyring()

        self.get_keyring().delete_password(service, user)
