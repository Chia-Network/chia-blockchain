import keyring as keyring_main

from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.file_keyring import FileKeyring
from chia.util.misc import prompt_yes_no
from keyrings.cryptfile.cryptfile import CryptFileKeyring  # pyright: reportMissingImports=false
from pathlib import Path
from sys import exit, platform
from typing import Any, Optional, Tuple, Union


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
    __root_path: Path

    # Instance members
    root_path: Path
    keyring: Union[Any, FileKeyring] = None
    cached_password: Optional[str] = DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD
    cached_password_is_validated: bool = False
    legacy_keyring = None

    def __init__(self, root_path: Path = DEFAULT_ROOT_PATH):
        """
        Initializes the keyring backend based on the OS. For Linux, we previously
        used CryptFileKeyring. We now use our own FileKeyring backend and migrate
        the data from the legacy CryptFileKeyring (on write).
        """
        self.root_path = root_path
        self.keyring = self._configure_backend()
        self.legacy_keyring = self._configure_legacy_backend()

        KeyringWrapper.__shared_instance = self

    def _configure_backend(self) -> Union[Any, FileKeyring]:
        if self.keyring:
            raise Exception("KeyringWrapper has already been instantiated")

        if platform == "win32" or platform == "cygwin":
            import keyring.backends.Windows

            keyring.set_keyring(keyring.backends.Windows.WinVaultKeyring())
        elif platform == "darwin":
            import keyring.backends.macOS

            keyring.set_keyring(keyring.backends.macOS.Keyring())
        elif platform == "linux":
            keyring = FileKeyring(root_path=self.root_path)  # type: ignore
        else:
            keyring = keyring_main

        return keyring

    def _configure_legacy_backend(self) -> CryptFileKeyring:
        # If keyring.yaml isn't found or is empty, check if we're using CryptFileKeyring
        filekeyring = self.keyring if type(self.keyring) == FileKeyring else None
        if filekeyring and not filekeyring.has_content():
            old_keyring = CryptFileKeyring()
            if Path(old_keyring.file_path).is_file():
                # After migrating content from legacy_keyring, we'll prompt to clear those keys
                old_keyring.keyring_key = "your keyring password"  # type: ignore
                return old_keyring
        return None

    @staticmethod
    def set_keyring_root_path(root_path: Path):
        """
        Used to set the root_path prior to instantiating the __shared_instance
        """
        KeyringWrapper.__root_path = root_path

    @staticmethod
    def get_shared_instance(create_if_necessary=True):
        if not KeyringWrapper.__shared_instance and create_if_necessary:
            KeyringWrapper(root_path=KeyringWrapper.__root_path)

        return KeyringWrapper.__shared_instance

    @staticmethod
    def cleanup_shared_instance():
        KeyringWrapper.__shared_instance = None

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

    def master_password_is_valid(self, password: str) -> bool:
        return self.keyring.check_password(password)

    def set_master_password(
        self, current_password: Optional[str], new_password: str, write_to_keyring: bool = True
    ) -> None:
        """
        Sets a new master password for the keyring
        """

        # Require a valid current_password
        if (
            self.has_master_password()
            and current_password is not None
            and not self.master_password_is_valid(current_password)
        ):
            raise ValueError("invalid current password")

        self.set_cached_master_password(new_password, validated=True)

        if write_to_keyring:
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

    def confirm_migration(self) -> bool:
        """
        Before beginning migration, we'll notify the user that the legacy keyring needs to be
        migrated and warn about backing up the mnemonic seeds.

        If a master password hasn't been explicitly set yet, we'll attempt to prompt and set
        the password prior to beginning migration.
        """

        master_password, _ = self.get_cached_master_password()
        if master_password == DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD:
            print(
                "\nYour existing keys need to be migrated to a new keyring that is optionally secured by a master "
                "password."
            )
            print("Would you like to set a master password now? Use 'chia password set' to change the password.\n")

            response = prompt_yes_no("Set keyring master password? (y/n) ")
            if response:
                from chia.cmds.password_funcs import prompt_for_new_password

                # Prompt for a master password and cache it
                new_password = prompt_for_new_password()
                self.set_master_password(current_password=None, new_password=new_password, write_to_keyring=False)
            else:
                print("Will skip setting a master password. Use 'chia password set' to set the master password.\n")
        else:
            import colorama

            colorama.init()

            print("\nYour existing keys will be migrated to a new keyring that is secured by your master password")
            print(colorama.Fore.YELLOW + colorama.Style.BRIGHT + "WARNING: " + colorama.Style.RESET_ALL, end="")
            print(
                "It is strongly recommended that you ensure you have a copy of the mnemonic seed for each of your "
                "keys prior to beginning migration\n"
            )

        return prompt_yes_no("Begin keyring migration? (y/n) ")

    def migrate_legacy_keyring(self):
        """
        Handle importing keys from the legacy keyring into the new keyring.

        Prior to beginning, we'll ensure that we at least suggest setting a master password
        and backing up mnemonic seeds. After importing keys from the legacy keyring, we'll
        perform a before/after comparison of the keyring contents, and on success we'll prompt
        to cleanup the legacy keyring.
        """

        from chia.util.keychain import Keychain, MAX_KEYS

        # Make sure the user is ready to begin migration. We want to ensure that
        response = self.confirm_migration()
        if not response:
            print("Skipping migration. Unable to proceed")
            exit(0)

        print("Migrating contents from legacy keyring")

        keychain = Keychain()
        # Obtain contents from the legacy keyring. When using the Keychain interface
        # to read, the legacy keyring will be preferred over the new keyring.
        original_private_keys = keychain.get_all_private_keys()
        service = keychain._get_service()
        user_password_pairs = []
        index = 0
        user = keychain._get_private_key_user(index)
        while index <= MAX_KEYS:
            # Build up a list of user/password tuples from the legacy keyring contents
            if user is not None:
                password = self.get_password(service, user)

            if password is not None:
                user_password_pairs.append((user, password))

            index += 1
            user = keychain._get_private_key_user(index)

        # Write the keys directly to the new keyring (self.keyring)
        for (user, password) in user_password_pairs:
            self.keyring.set_password(service, user, password)

        # Stop using the legacy keyring. This will direct subsequent reads to the new keyring.
        old_keyring = self.legacy_keyring
        self.legacy_keyring = None

        print("Verifying migration results...", end="")

        # Compare the original keyring contents with the new
        try:
            post_migration_private_keys = keychain.get_all_private_keys()

            if post_migration_private_keys == original_private_keys:
                print(" Verified")
        except Exception as e:
            print(f"\nMigration failed: {e}")
            print("Leaving legacy keyring intact")
            exit(1)

        print(f"Keyring migration completed successfully ({str(self.keyring.keyring_path)})\n")

        # Ask if we should clean up the legacy keyring
        self.confirm_legacy_keyring_cleanup(old_keyring, service, [user for (user, _) in user_password_pairs])

    def confirm_legacy_keyring_cleanup(self, legacy_keyring, service, users):
        """
        Ask the user whether we should remove keys from the legacy keyring. We can't just
        delete the file because other python processes might use the same keyring file.
        """

        response = prompt_yes_no(f"Remove keys from old keyring ({str(legacy_keyring.file_path)})? (y/n) ")

        if response:
            for user in users:
                legacy_keyring.delete_password(service, user)
            print("Removed keys from old keyring")
        else:
            print("Keys in old keyring left intact")

        # TODO: CryptFileKeyring doesn't cleanup section headers
        # [chia_2Duser_2Dchia_2D1_2E8] is left behind

    # Keyring interface

    def get_password(self, service: str, user: str) -> str:
        # Continue reading from the legacy keyring until we want to write something,
        # at which point we'll migrate the legacy contents to the new keyring
        if self.using_legacy_keyring():
            return self.legacy_keyring.get_password(service, user)  # type: ignore

        return self.get_keyring().get_password(service, user)

    def set_password(self, service: str, user: str, password_bytes: bytes):
        # On the first write while using the legacy keyring, we'll start migration
        if self.using_legacy_keyring() and self.has_cached_master_password():
            self.migrate_legacy_keyring()

        self.get_keyring().set_password(service, user, password_bytes)

    def delete_password(self, service: str, user: str):
        # On the first write while using the legacy keyring, we'll start migration
        if self.using_legacy_keyring() and self.has_cached_master_password():
            self.migrate_legacy_keyring()

        self.get_keyring().delete_password(service, user)
