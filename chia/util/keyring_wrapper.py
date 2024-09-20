from __future__ import annotations

from pathlib import Path
from sys import platform
from typing import ClassVar, Optional, Tuple, Union, overload

from keyring.backends.macOS import Keyring as MacKeyring
from keyring.backends.Windows import WinVaultKeyring as WinKeyring
from keyring.errors import KeyringError, PasswordDeleteError
from typing_extensions import Literal

from chia.util.default_root import DEFAULT_KEYS_ROOT_PATH
from chia.util.file_keyring import FileKeyring

# We want to protect the keyring, even if a user-specified master passphrase isn't provided
#
# WARNING: Changing the default passphrase will prevent passphrase-less users from accessing
# their existing keys. Using a new default passphrase requires migrating existing users to
# the new passphrase.
DEFAULT_PASSPHRASE_IF_NO_MASTER_PASSPHRASE = "$ chia passphrase set # all the cool kids are doing it!"

MASTER_PASSPHRASE_SERVICE_NAME = "Chia Passphrase"
MASTER_PASSPHRASE_USER_NAME = "Chia Passphrase"


OSPassphraseStore = Union[MacKeyring, WinKeyring]


def get_os_passphrase_store() -> Optional[OSPassphraseStore]:
    if platform == "darwin":
        return MacKeyring()  # type: ignore[no-untyped-call]
    elif platform == "win32" or platform == "cygwin":
        return WinKeyring()  # type: ignore[no-untyped-call]
    return None


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
    related to the master passphrase.
    """

    # Static members
    __shared_instance: ClassVar[Optional[KeyringWrapper]] = None
    __keys_root_path: ClassVar[Path] = DEFAULT_KEYS_ROOT_PATH

    # Instance members
    keys_root_path: Path
    keyring: FileKeyring
    cached_passphrase: Optional[str] = None
    cached_passphrase_is_validated: bool = False

    def __init__(self, keys_root_path: Path = DEFAULT_KEYS_ROOT_PATH):
        """
        Initializes the keyring backend.
        """

        self.keys_root_path = keys_root_path
        self.keyring = self._configure_backend()

        # Initialize the cached_passphrase
        self.cached_passphrase = self._get_initial_cached_passphrase()

    def _configure_backend(self) -> FileKeyring:
        return FileKeyring.create(keys_root_path=self.keys_root_path)

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
    def set_keys_root_path(keys_root_path: Path) -> None:
        """
        Used to set the keys_root_path prior to instantiating the __shared_instance
        """
        KeyringWrapper.__keys_root_path = keys_root_path

    @overload
    @staticmethod
    def get_shared_instance() -> KeyringWrapper: ...

    @overload
    @staticmethod
    def get_shared_instance(create_if_necessary: Literal[True]) -> KeyringWrapper: ...

    @overload
    @staticmethod
    def get_shared_instance(create_if_necessary: bool) -> Optional[KeyringWrapper]: ...

    @staticmethod
    def get_shared_instance(create_if_necessary: bool = True) -> Optional[KeyringWrapper]:
        if not KeyringWrapper.__shared_instance and create_if_necessary:
            KeyringWrapper.__shared_instance = KeyringWrapper(keys_root_path=KeyringWrapper.__keys_root_path)

        return KeyringWrapper.__shared_instance

    @staticmethod
    def cleanup_shared_instance() -> None:
        KeyringWrapper.__shared_instance = None

    def get_keyring(self) -> FileKeyring:
        """
        Return the current keyring backend.
        """
        return self.keyring

    # Master passphrase support

    def get_cached_master_passphrase(self) -> Tuple[Optional[str], bool]:
        """
        Returns a tuple including the currently cached passphrase and a bool
        indicating whether the passphrase has been previously validated.
        """
        return self.cached_passphrase, self.cached_passphrase_is_validated

    def set_cached_master_passphrase(self, passphrase: Optional[str], validated: bool = False) -> None:
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
        return self.keyring.has_content()

    def master_passphrase_is_valid(self, passphrase: str, force_reload: bool = False) -> bool:
        return self.keyring.check_passphrase(passphrase, force_reload=force_reload)

    def set_master_passphrase(
        self,
        current_passphrase: Optional[str],
        new_passphrase: str,
        *,
        write_to_keyring: bool = True,
        passphrase_hint: Optional[str] = None,
        save_passphrase: bool = False,
    ) -> None:
        """
        Sets a new master passphrase for the keyring
        """
        from chia.util.errors import KeychainCurrentPassphraseIsInvalid
        from chia.util.keychain import supports_os_passphrase_storage

        # Require a valid current_passphrase
        if (
            self.has_master_passphrase()
            and current_passphrase is not None
            and not self.master_passphrase_is_valid(current_passphrase)
        ):
            raise KeychainCurrentPassphraseIsInvalid()

        self.set_cached_master_passphrase(new_passphrase, validated=True)

        self.keyring.set_passphrase_hint(passphrase_hint)

        if write_to_keyring:
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
                passphrase_store.set_password(
                    MASTER_PASSPHRASE_SERVICE_NAME,
                    MASTER_PASSPHRASE_USER_NAME,
                    passphrase,
                )
            except KeyringError as e:
                if not warn_if_macos_errSecInteractionNotAllowed(e):
                    raise
        return None

    def remove_master_passphrase_from_credential_store(self) -> None:
        passphrase_store: Optional[OSPassphraseStore] = get_os_passphrase_store()
        if passphrase_store is not None:
            try:
                passphrase_store.delete_password(
                    MASTER_PASSPHRASE_SERVICE_NAME,
                    MASTER_PASSPHRASE_USER_NAME,
                )
            except PasswordDeleteError:
                if (
                    passphrase_store.get_credential(MASTER_PASSPHRASE_SERVICE_NAME, MASTER_PASSPHRASE_USER_NAME)
                    is not None
                ):
                    raise
            except KeyringError as e:
                if not warn_if_macos_errSecInteractionNotAllowed(e):
                    raise
        return None

    def get_master_passphrase_from_credential_store(self) -> Optional[str]:
        passphrase_store: Optional[OSPassphraseStore] = get_os_passphrase_store()
        if passphrase_store is not None:
            try:
                return passphrase_store.get_password(  # type: ignore[no-any-return]
                    MASTER_PASSPHRASE_SERVICE_NAME,
                    MASTER_PASSPHRASE_USER_NAME,
                )
            except KeyringError as e:
                if not warn_if_macos_errSecInteractionNotAllowed(e):
                    raise
        return None

    def get_master_passphrase_hint(self) -> Optional[str]:
        return self.keyring.get_passphrase_hint()
