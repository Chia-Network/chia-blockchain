import asyncio
import keyring as keyring_main

from blspy import PrivateKey  # pyright: reportMissingImports=false
from chia.util.default_root import DEFAULT_KEYS_ROOT_PATH
from chia.util.file_keyring import FileKeyring
from chia.util.misc import prompt_yes_no
from keyrings.cryptfile.cryptfile import CryptFileKeyring  # pyright: reportMissingImports=false
from keyring.backends.macOS import Keyring as MacKeyring
from keyring.backends.Windows import WinVaultKeyring as WinKeyring
from keyring.errors import KeyringError, PasswordDeleteError
from pathlib import Path
from sys import exit, platform
from typing import Any, List, Optional, Tuple, Type, Union


# We want to protect the keyring, even if a user-specified master passphrase isn't provided
#
# WARNING: Changing the default passphrase will prevent passphrase-less users from accessing
# their existing keys. Using a new default passphrase requires migrating existing users to
# the new passphrase.
DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE = "$ chia passphrase set # all the cool kids are doing it!"

MASTER_PASSPHRASE_SERVICE_NAME = "Chia Passphrase"
MASTER_PASSPHRASE_USER_NAME = "Chia Passphrase"


LegacyKeyring = Union[MacKeyring, WinKeyring, CryptFileKeyring]
OSPassphraseStore = Union[MacKeyring, WinKeyring]


def get_legacy_keyring_instance() -> Optional[LegacyKeyring]:
    if platform == "darwin":
        return MacKeyring()
    elif platform == "win32" or platform == "cygwin":
        return WinKeyring()
    elif platform == "linux":
        keyring: CryptFileKeyring = CryptFileKeyring()
        keyring.keyring_key = "your keyring password"  # type: ignore
        return keyring
    return None


def get_os_passphrase_store() -> Optional[OSPassphraseStore]:
    if platform == "darwin":
        return MacKeyring()
    elif platform == "win32" or platform == "cygwin":
        return WinKeyring()
    return None


def check_legacy_keyring_keys_present(keyring: Union[MacKeyring, WinKeyring]) -> bool:
    from keyring.credentials import SimpleCredential
    from chia.util.keychain import default_keychain_user, default_keychain_service, get_private_key_user, MAX_KEYS

    keychain_user: str = default_keychain_user()
    keychain_service: str = default_keychain_service()

    for index in range(0, MAX_KEYS):
        current_user: str = get_private_key_user(keychain_user, index)
        credential: Optional[SimpleCredential] = keyring.get_credential(keychain_service, current_user)
        if credential is not None:
            return True
    return False


def warn_if_macos_errSecInteractionNotAllowed(error: KeyringError) -> bool:
    """
    Check if the macOS Keychain error is errSecInteractionNotAllowed. This commonly
    occurs when the keychain is accessed while headless (such as remoting into a Mac
    via SSH). Because macOS Keychain operations may require prompting for login creds,
    a connection to the WindowServer is required. Returns True if the error was
    handled.
    """

    if "-25308" in str(error):
        print(
            "WARNING: Unable to access the macOS Keychain (-25308 errSecInteractionNotAllowed). "
            "Are you logged-in remotely?"
        )
        return True
    return False


class KeyringWrapper:
    """
    KeyringWrapper provides an abstraction that the Keychain class can use
    without requiring knowledge of the keyring backend. During initialization,
    a keyring backend is selected based on the OS.

    The wrapper is implemented as a singleton, as it may need to manage state
    related to the master passphrase and handle migration from the legacy
    CryptFileKeyring implementation.
    """

    # Static members
    __shared_instance = None
    __keys_root_path: Path = DEFAULT_KEYS_ROOT_PATH

    # Instance members
    keys_root_path: Path
    keyring: Union[Any, FileKeyring] = None
    cached_passphrase: Optional[str] = None
    cached_passphrase_is_validated: bool = False
    legacy_keyring = None

    def __init__(self, keys_root_path: Path = DEFAULT_KEYS_ROOT_PATH):
        """
        Initializes the keyring backend based on the OS. For Linux, we previously
        used CryptFileKeyring. We now use our own FileKeyring backend and migrate
        the data from the legacy CryptFileKeyring (on write).
        """
        self.keys_root_path = keys_root_path
        self.refresh_keyrings()

    def refresh_keyrings(self):
        self.keyring = None
        self.keyring = self._configure_backend()

        # Configure the legacy keyring if keyring passphrases are supported to support migration (if necessary)
        self.legacy_keyring = self._configure_legacy_backend()

        # Initialize the cached_passphrase
        self.cached_passphrase = self._get_initial_cached_passphrase()

    def _configure_backend(self) -> Union[LegacyKeyring, FileKeyring]:
        from chia.util.keychain import supports_keyring_passphrase

        keyring: Union[LegacyKeyring, FileKeyring]

        if self.keyring:
            raise Exception("KeyringWrapper has already been instantiated")

        if supports_keyring_passphrase():
            keyring = FileKeyring(keys_root_path=self.keys_root_path)  # type: ignore
        else:
            legacy_keyring: Optional[LegacyKeyring] = get_legacy_keyring_instance()
            if legacy_keyring is None:
                legacy_keyring = keyring_main
            else:
                keyring_main.set_keyring(legacy_keyring)
            keyring = legacy_keyring

        return keyring

    def _configure_legacy_backend(self) -> LegacyKeyring:
        # If keyring.yaml isn't found or is empty, check if we're using
        # CryptFileKeyring, Mac Keychain, or Windows Credential Manager
        filekeyring = self.keyring if type(self.keyring) == FileKeyring else None
        if filekeyring and not filekeyring.has_content():
            keyring: Optional[LegacyKeyring] = get_legacy_keyring_instance()
            if keyring is not None and check_legacy_keyring_keys_present(keyring):
                return keyring
        return None

    def _get_initial_cached_passphrase(self) -> str:
        """
        Grab the saved passphrase from the OS credential store (if available), otherwise
        use the default passphrase
        """
        from chia.util.keychain import supports_os_passphrase_storage

        passphrase: Optional[str] = None

        if supports_os_passphrase_storage():
            passphrase = self.get_master_passphrase_from_credential_store()

        if passphrase is None:
            passphrase = DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE

        return passphrase

    @staticmethod
    def set_keys_root_path(keys_root_path: Path):
        """
        Used to set the keys_root_path prior to instantiating the __shared_instance
        """
        KeyringWrapper.__keys_root_path = keys_root_path

    @staticmethod
    def get_shared_instance(create_if_necessary=True):
        if not KeyringWrapper.__shared_instance and create_if_necessary:
            KeyringWrapper.__shared_instance = KeyringWrapper(keys_root_path=KeyringWrapper.__keys_root_path)

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

    # Master passphrase support

    def keyring_supports_master_passphrase(self) -> bool:
        return type(self.get_keyring()) in [FileKeyring]

    def get_cached_master_passphrase(self) -> Tuple[Optional[str], bool]:
        """
        Returns a tuple including the currently cached passphrase and a bool
        indicating whether the passphrase has been previously validated.
        """
        return self.cached_passphrase, self.cached_passphrase_is_validated

    def set_cached_master_passphrase(self, passphrase: Optional[str], validated=False) -> None:
        """
        Cache the provided passphrase and optionally indicate whether the passphrase
        has been validated.
        """
        self.cached_passphrase = passphrase
        self.cached_passphrase_is_validated = validated

    def has_cached_master_passphrase(self) -> bool:
        passphrase = self.get_cached_master_passphrase()
        return passphrase is not None and len(passphrase) > 0

    def has_master_passphrase(self) -> bool:
        """
        Returns a bool indicating whether the underlying keyring data
        is secured by a master passphrase.
        """
        return self.keyring_supports_master_passphrase() and self.keyring.has_content()

    def master_passphrase_is_valid(self, passphrase: str, force_reload: bool = False) -> bool:
        return self.keyring.check_passphrase(passphrase, force_reload=force_reload)

    def set_master_passphrase(
        self,
        current_passphrase: Optional[str],
        new_passphrase: str,
        *,
        write_to_keyring: bool = True,
        allow_migration: bool = True,
        passphrase_hint: Optional[str] = None,
        save_passphrase: bool = False,
    ) -> None:
        """
        Sets a new master passphrase for the keyring
        """

        from chia.util.keychain import (
            KeyringCurrentPassphraseIsInvalid,
            KeyringRequiresMigration,
            supports_os_passphrase_storage,
        )

        # Require a valid current_passphrase
        if (
            self.has_master_passphrase()
            and current_passphrase is not None
            and not self.master_passphrase_is_valid(current_passphrase)
        ):
            raise KeyringCurrentPassphraseIsInvalid("invalid current passphrase")

        self.set_cached_master_passphrase(new_passphrase, validated=True)

        self.keyring.set_passphrase_hint(passphrase_hint)

        if write_to_keyring:
            # We'll migrate the legacy contents to the new keyring at this point
            if self.using_legacy_keyring():
                if not allow_migration:
                    raise KeyringRequiresMigration("keyring requires migration")

                self.migrate_legacy_keyring_interactive()
            else:
                # We're reencrypting the keyring contents using the new passphrase. Ensure that the
                # payload has been decrypted by calling load_keyring with the current passphrase.
                self.keyring.load_keyring(passphrase=current_passphrase)
                self.keyring.write_keyring(fresh_salt=True)  # Create a new salt since we're changing the passphrase

        if supports_os_passphrase_storage():
            if save_passphrase:
                self.save_master_passphrase_to_credential_store(new_passphrase)
            else:
                self.remove_master_passphrase_from_credential_store()

    def remove_master_passphrase(self, current_passphrase: Optional[str]) -> None:
        """
        Remove the user-specific master passphrase. We still keep the keyring contents encrypted
        using the default passphrase.
        """
        self.set_master_passphrase(current_passphrase, DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE)

    def save_master_passphrase_to_credential_store(self, passphrase: str) -> None:
        passphrase_store: Optional[OSPassphraseStore] = get_os_passphrase_store()
        if passphrase_store is not None:
            try:
                passphrase_store.set_password(MASTER_PASSPHRASE_SERVICE_NAME, MASTER_PASSPHRASE_USER_NAME, passphrase)
            except KeyringError as e:
                if not warn_if_macos_errSecInteractionNotAllowed(e):
                    raise e
        return None

    def remove_master_passphrase_from_credential_store(self) -> None:
        passphrase_store: Optional[OSPassphraseStore] = get_os_passphrase_store()
        if passphrase_store is not None:
            try:
                passphrase_store.delete_password(MASTER_PASSPHRASE_SERVICE_NAME, MASTER_PASSPHRASE_USER_NAME)
            except PasswordDeleteError as e:
                if (
                    passphrase_store.get_credential(MASTER_PASSPHRASE_SERVICE_NAME, MASTER_PASSPHRASE_USER_NAME)
                    is not None
                ):
                    raise e
            except KeyringError as e:
                if not warn_if_macos_errSecInteractionNotAllowed(e):
                    raise e
        return None

    def get_master_passphrase_from_credential_store(self) -> Optional[str]:
        passphrase_store: Optional[OSPassphraseStore] = get_os_passphrase_store()
        if passphrase_store is not None:
            try:
                return passphrase_store.get_password(MASTER_PASSPHRASE_SERVICE_NAME, MASTER_PASSPHRASE_USER_NAME)
            except KeyringError as e:
                if not warn_if_macos_errSecInteractionNotAllowed(e):
                    raise e
        return None

    def get_master_passphrase_hint(self) -> Optional[str]:
        if self.keyring_supports_master_passphrase():
            return self.keyring.get_passphrase_hint()
        return None

    # Legacy keyring migration

    class MigrationResults:
        def __init__(
            self,
            original_private_keys: List[Tuple[PrivateKey, bytes]],
            legacy_keyring: LegacyKeyring,
            keychain_service: str,
            keychain_users: List[str],
        ):
            self.original_private_keys = original_private_keys
            self.legacy_keyring = legacy_keyring
            self.keychain_service = keychain_service
            self.keychain_users = keychain_users

    def confirm_migration(self) -> bool:
        """
        Before beginning migration, we'll notify the user that the legacy keyring needs to be
        migrated and warn about backing up the mnemonic seeds.

        If a master passphrase hasn't been explicitly set yet, we'll attempt to prompt and set
        the passphrase prior to beginning migration.
        """

        master_passphrase, _ = self.get_cached_master_passphrase()
        if master_passphrase == DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE:
            print(
                "\nYour existing keys need to be migrated to a new keyring that is optionally secured by a master "
                "passphrase."
            )
            print(
                "Would you like to set a master passphrase now? Use 'sit passphrase set' to change the passphrase.\n"
            )

            response = prompt_yes_no("Set keyring master passphrase? (y/n) ")
            if response:
                from chia.cmds.passphrase_funcs import prompt_for_new_passphrase

                # Prompt for a master passphrase and cache it
                new_passphrase, save_passphrase = prompt_for_new_passphrase()
                self.set_master_passphrase(
                    current_passphrase=None,
                    new_passphrase=new_passphrase,
                    write_to_keyring=False,
                    save_passphrase=save_passphrase,
                )
            else:
                print(
                    "Will skip setting a master passphrase. Use 'sit passphrase set' to set the master passphrase.\n"
                )
        else:
            import colorama

            colorama.init()

            print("\nYour existing keys will be migrated to a new keyring that is secured by your master passphrase")
            print(colorama.Fore.YELLOW + colorama.Style.BRIGHT + "WARNING: " + colorama.Style.RESET_ALL, end="")
            print(
                "It is strongly recommended that you ensure you have a copy of the mnemonic seed for each of your "
                "keys prior to beginning migration\n"
            )

        return prompt_yes_no("Begin keyring migration? (y/n) ")

    def migrate_legacy_keys(self) -> MigrationResults:
        from chia.util.keychain import get_private_key_user, Keychain, MAX_KEYS

        print("Migrating contents from legacy keyring")

        keychain: Keychain = Keychain()
        # Obtain contents from the legacy keyring. When using the Keychain interface
        # to read, the legacy keyring will be preferred over the new keyring.
        original_private_keys = keychain.get_all_private_keys()
        service = keychain.service
        user_passphrase_pairs = []
        index = 0
        user = get_private_key_user(keychain.user, index)
        while index <= MAX_KEYS:
            # Build up a list of user/passphrase tuples from the legacy keyring contents
            if user is not None:
                passphrase = self.get_passphrase(service, user)

            if passphrase is not None:
                user_passphrase_pairs.append((user, passphrase))

            index += 1
            user = get_private_key_user(keychain.user, index)

        # Write the keys directly to the new keyring (self.keyring)
        for (user, passphrase) in user_passphrase_pairs:
            self.keyring.set_password(service, user, passphrase)

        return KeyringWrapper.MigrationResults(
            original_private_keys, self.legacy_keyring, service, [user for (user, _) in user_passphrase_pairs]
        )

    def verify_migration_results(self, migration_results: MigrationResults) -> bool:
        from chia.util.keychain import Keychain

        # Stop using the legacy keyring. This will direct subsequent reads to the new keyring.
        self.legacy_keyring = None
        success: bool = False

        print("Verifying migration results...", end="")

        # Compare the original keyring contents with the new
        try:
            keychain: Keychain = Keychain()
            original_private_keys = migration_results.original_private_keys
            post_migration_private_keys = keychain.get_all_private_keys()

            # Sort the key collections prior to comparing
            original_private_keys.sort(key=lambda e: str(e[0]))
            post_migration_private_keys.sort(key=lambda e: str(e[0]))

            if post_migration_private_keys == original_private_keys:
                success = True
                print(" Verified")
            else:
                print(" Failed")
                raise ValueError("Migrated keys don't match original keys")
        except Exception as e:
            print(f"\nMigration failed: {e}")
            print("Leaving legacy keyring intact")
            self.legacy_keyring = migration_results.legacy_keyring  # Restore the legacy keyring
            raise e

        return success

    def confirm_legacy_keyring_cleanup(self, migration_results) -> bool:
        """
        Ask the user whether we should remove keys from the legacy keyring. In the case
        of CryptFileKeyring, we can't just delete the file because other python processes
        might use the same keyring file.
        """
        keyring_name: str = ""
        legacy_keyring_type: Type = type(migration_results.legacy_keyring)

        if legacy_keyring_type is CryptFileKeyring:
            keyring_name = str(migration_results.legacy_keyring.file_path)
        elif legacy_keyring_type is MacKeyring:
            keyring_name = "macOS Keychain"
        elif legacy_keyring_type is WinKeyring:
            keyring_name = "Windows Credential Manager"

        prompt = "Remove keys from old keyring"
        if len(keyring_name) > 0:
            prompt += f" ({keyring_name})?"
        else:
            prompt += "?"
        prompt += " (y/n) "
        return prompt_yes_no(prompt)

    def cleanup_legacy_keyring(self, migration_results: MigrationResults):
        for user in migration_results.keychain_users:
            migration_results.legacy_keyring.delete_password(migration_results.keychain_service, user)

    def migrate_legacy_keyring(self, cleanup_legacy_keyring: bool = False):
        results = self.migrate_legacy_keys()
        success = self.verify_migration_results(results)

        if success and cleanup_legacy_keyring:
            self.cleanup_legacy_keyring(results)

    def migrate_legacy_keyring_interactive(self):
        """
        Handle importing keys from the legacy keyring into the new keyring.

        Prior to beginning, we'll ensure that we at least suggest setting a master passphrase
        and backing up mnemonic seeds. After importing keys from the legacy keyring, we'll
        perform a before/after comparison of the keyring contents, and on success we'll prompt
        to cleanup the legacy keyring.
        """
        from chia.cmds.passphrase_funcs import async_update_daemon_migration_completed_if_running

        # Make sure the user is ready to begin migration.
        response = self.confirm_migration()
        if not response:
            print("Skipping migration. Unable to proceed")
            exit(0)

        try:
            results = self.migrate_legacy_keys()
            success = self.verify_migration_results(results)

            if success:
                print(f"Keyring migration completed successfully ({str(self.keyring.keyring_path)})\n")
        except Exception as e:
            print(f"\nMigration failed: {e}")
            print("Leaving legacy keyring intact")
            exit(1)

        # Ask if we should clean up the legacy keyring
        if self.confirm_legacy_keyring_cleanup(results):
            self.cleanup_legacy_keyring(results)
            print("Removed keys from old keyring")
        else:
            print("Keys in old keyring left intact")

        # Notify the daemon (if running) that migration has completed
        asyncio.get_event_loop().run_until_complete(async_update_daemon_migration_completed_if_running())

    # Keyring interface

    def get_passphrase(self, service: str, user: str) -> str:
        # Continue reading from the legacy keyring until we want to write something,
        # at which point we'll migrate the legacy contents to the new keyring
        if self.using_legacy_keyring():
            return self.legacy_keyring.get_password(service, user)  # type: ignore

        return self.get_keyring().get_password(service, user)

    def set_passphrase(self, service: str, user: str, passphrase: str):
        # On the first write while using the legacy keyring, we'll start migration
        if self.using_legacy_keyring() and self.has_cached_master_passphrase():
            self.migrate_legacy_keyring_interactive()

        self.get_keyring().set_password(service, user, passphrase)

    def delete_passphrase(self, service: str, user: str):
        # On the first write while using the legacy keyring, we'll start migration
        if self.using_legacy_keyring() and self.has_cached_master_passphrase():
            self.migrate_legacy_keyring_interactive()

        self.get_keyring().delete_password(service, user)
