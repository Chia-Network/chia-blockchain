import colorama
import pkg_resources
import sys
import unicodedata

from bitstring import BitArray  # pyright: reportMissingImports=false
from blspy import AugSchemeMPL, G1Element, PrivateKey  # pyright: reportMissingImports=false
from chia.util.errors import KeychainNotSet, KeychainMaxUnlockAttempts, KeychainFingerprintExists
from chia.util.hash import std_hash
from chia.util.keyring_wrapper import KeyringWrapper
from hashlib import pbkdf2_hmac
from pathlib import Path
from secrets import token_bytes
from time import sleep
from typing import Any, Dict, List, Optional, Tuple


CURRENT_KEY_VERSION = "1.8"
DEFAULT_USER = f"user-chia-{CURRENT_KEY_VERSION}"  # e.g. user-chia-1.8
DEFAULT_SERVICE = f"chia-{DEFAULT_USER}"  # e.g. chia-user-chia-1.8
DEFAULT_PASSPHRASE_PROMPT = (
    colorama.Fore.YELLOW + colorama.Style.BRIGHT + "(Unlock Keyring)" + colorama.Style.RESET_ALL + " Passphrase: "
)  # noqa: E501
FAILED_ATTEMPT_DELAY = 0.5
MAX_KEYS = 100
MAX_RETRIES = 3
MIN_PASSPHRASE_LEN = 8


def supports_os_passphrase_storage() -> bool:
    return sys.platform in ["darwin", "win32", "cygwin"]


def passphrase_requirements() -> Dict[str, Any]:
    """
    Returns a dictionary specifying current passphrase requirements
    """
    return {"is_optional": True, "min_length": MIN_PASSPHRASE_LEN}  # lgtm [py/clear-text-logging-sensitive-data]


def set_keys_root_path(keys_root_path: Path) -> None:
    """
    Used to set the keys_root_path prior to instantiating the KeyringWrapper shared instance.
    """
    KeyringWrapper.set_keys_root_path(keys_root_path)


def obtain_current_passphrase(prompt: str = DEFAULT_PASSPHRASE_PROMPT, use_passphrase_cache: bool = False) -> str:
    """
    Obtains the master passphrase for the keyring, optionally using the cached
    value (if previously set). If the passphrase isn't already cached, the user is
    prompted interactively to enter their passphrase a max of MAX_RETRIES times
    before failing.
    """
    from chia.cmds.passphrase_funcs import prompt_for_passphrase

    if use_passphrase_cache:
        passphrase, validated = KeyringWrapper.get_shared_instance().get_cached_master_passphrase()
        if passphrase:
            # If the cached passphrase was previously validated, we assume it's... valid
            if validated:
                return passphrase

            # Cached passphrase needs to be validated
            if KeyringWrapper.get_shared_instance().master_passphrase_is_valid(passphrase):
                KeyringWrapper.get_shared_instance().set_cached_master_passphrase(passphrase, validated=True)
                return passphrase
            else:
                # Cached passphrase is bad, clear the cache
                KeyringWrapper.get_shared_instance().set_cached_master_passphrase(None)

    # Prompt interactively with up to MAX_RETRIES attempts
    for i in range(MAX_RETRIES):
        colorama.init()

        passphrase = prompt_for_passphrase(prompt)

        if KeyringWrapper.get_shared_instance().master_passphrase_is_valid(passphrase):
            # If using the passphrase cache, and the user inputted a passphrase, update the cache
            if use_passphrase_cache:
                KeyringWrapper.get_shared_instance().set_cached_master_passphrase(passphrase, validated=True)
            return passphrase

        sleep(FAILED_ATTEMPT_DELAY)
        print("Incorrect passphrase\n")
    raise KeychainMaxUnlockAttempts()


def unlocks_keyring(use_passphrase_cache=False):
    """
    Decorator used to unlock the keyring interactively, if necessary
    """

    def inner(func):
        def wrapper(*args, **kwargs):
            try:
                if KeyringWrapper.get_shared_instance().has_master_passphrase():
                    obtain_current_passphrase(use_passphrase_cache=use_passphrase_cache)
            except Exception as e:
                print(f"Unable to unlock the keyring: {e}")
                sys.exit(1)
            return func(*args, **kwargs)

        return wrapper

    return inner


def bip39_word_list() -> str:
    return pkg_resources.resource_string(__name__, "english.txt").decode()


def generate_mnemonic() -> str:
    mnemonic_bytes = token_bytes(32)
    mnemonic = bytes_to_mnemonic(mnemonic_bytes)
    return mnemonic


def bytes_to_mnemonic(mnemonic_bytes: bytes) -> str:
    if len(mnemonic_bytes) not in [16, 20, 24, 28, 32]:
        raise ValueError(
            f"Data length should be one of the following: [16, 20, 24, 28, 32], but it is {len(mnemonic_bytes)}."
        )
    word_list = bip39_word_list().splitlines()
    CS = len(mnemonic_bytes) // 4

    checksum = BitArray(bytes(std_hash(mnemonic_bytes)))[:CS]

    bitarray = BitArray(mnemonic_bytes) + checksum
    mnemonics = []
    assert len(bitarray) % 11 == 0

    for i in range(0, len(bitarray) // 11):
        start = i * 11
        end = start + 11
        bits = bitarray[start:end]
        m_word_position = bits.uint
        m_word = word_list[m_word_position]
        mnemonics.append(m_word)

    return " ".join(mnemonics)


def bytes_from_mnemonic(mnemonic_str: str) -> bytes:
    mnemonic: List[str] = mnemonic_str.split(" ")
    if len(mnemonic) not in [12, 15, 18, 21, 24]:
        raise ValueError("Invalid mnemonic length")

    word_list = {word: i for i, word in enumerate(bip39_word_list().splitlines())}
    bit_array = BitArray()
    for i in range(0, len(mnemonic)):
        word = mnemonic[i]
        if word not in word_list:
            raise ValueError(f"'{word}' is not in the mnemonic dictionary; may be misspelled")
        value = word_list[word]
        bit_array.append(BitArray(uint=value, length=11))

    CS: int = len(mnemonic) // 3
    ENT: int = len(mnemonic) * 11 - CS
    assert len(bit_array) == len(mnemonic) * 11
    assert ENT % 32 == 0

    entropy_bytes = bit_array[:ENT].bytes
    checksum_bytes = bit_array[ENT:]
    checksum = BitArray(std_hash(entropy_bytes))[:CS]

    assert len(checksum_bytes) == CS

    if checksum != checksum_bytes:
        raise ValueError("Invalid order of mnemonic words")

    return entropy_bytes


def mnemonic_to_seed(mnemonic: str) -> bytes:
    """
    Uses BIP39 standard to derive a seed from entropy bytes.
    """
    salt_str: str = "mnemonic"
    salt = unicodedata.normalize("NFKD", salt_str).encode("utf-8")
    mnemonic_normalized = unicodedata.normalize("NFKD", mnemonic).encode("utf-8")
    seed = pbkdf2_hmac("sha512", mnemonic_normalized, salt, 2048)

    assert len(seed) == 64
    return seed


def default_keychain_user() -> str:
    return DEFAULT_USER


def default_keychain_service() -> str:
    return DEFAULT_SERVICE


def get_private_key_user(user: str, index: int) -> str:
    """
    Returns the keychain user string for a key index.
    """
    return f"wallet-{user}-{index}"


class Keychain:
    """
    The keychain stores two types of keys: private keys, which are PrivateKeys from blspy,
    and private key seeds, which are bytes objects that are used as a seed to construct
    PrivateKeys. Private key seeds are converted to mnemonics when shown to users.

    Both types of keys are stored as hex strings in the python keyring, and the implementation of
    the keyring depends on OS. Both types of keys can be added, and get_private_keys returns a
    list of all keys.
    """

    def __init__(self, user: Optional[str] = None, service: Optional[str] = None, force_legacy: bool = False):
        self.user = user if user is not None else default_keychain_user()
        self.service = service if service is not None else default_keychain_service()

        keyring_wrapper: Optional[KeyringWrapper] = (
            KeyringWrapper.get_legacy_instance() if force_legacy else KeyringWrapper.get_shared_instance()
        )

        if keyring_wrapper is None:
            raise KeychainNotSet(f"KeyringWrapper not set: force_legacy={force_legacy}")

        self.keyring_wrapper = keyring_wrapper

    def _get_pk_and_entropy(self, user: str) -> Optional[Tuple[G1Element, bytes]]:
        """
        Returns the keychain contents for a specific 'user' (key index). The contents
        include an G1Element and the entropy required to generate the private key.
        Note that generating the actual private key also requires the passphrase.
        """
        read_str = self.keyring_wrapper.get_passphrase(self.service, user)
        if read_str is None or len(read_str) == 0:
            return None
        str_bytes = bytes.fromhex(read_str)
        return (
            G1Element.from_bytes(str_bytes[: G1Element.SIZE]),
            str_bytes[G1Element.SIZE :],  # flake8: noqa
        )

    def _get_free_private_key_index(self) -> int:
        """
        Get the index of the first free spot in the keychain.
        """
        index = 0
        while True:
            pk = get_private_key_user(self.user, index)
            pkent = self._get_pk_and_entropy(pk)
            if pkent is None:
                return index
            index += 1

    @unlocks_keyring(use_passphrase_cache=True)
    def add_private_key(self, mnemonic: str) -> PrivateKey:
        """
        Adds a private key to the keychain, with the given entropy and passphrase. The
        keychain itself will store the public key, and the entropy bytes,
        but not the passphrase.
        """
        seed = mnemonic_to_seed(mnemonic)
        entropy = bytes_from_mnemonic(mnemonic)
        index = self._get_free_private_key_index()
        key = AugSchemeMPL.key_gen(seed)
        fingerprint = key.get_g1().get_fingerprint()

        if fingerprint in [pk.get_fingerprint() for pk in self.get_all_public_keys()]:
            # Prevents duplicate add
            raise KeychainFingerprintExists(fingerprint)

        self.keyring_wrapper.set_passphrase(
            self.service,
            get_private_key_user(self.user, index),
            bytes(key.get_g1()).hex() + entropy.hex(),
        )
        return key

    def get_first_private_key(self) -> Optional[Tuple[PrivateKey, bytes]]:
        """
        Returns the first key in the keychain that has one of the passed in passphrases.
        """
        index = 0
        pkent = self._get_pk_and_entropy(get_private_key_user(self.user, index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                mnemonic = bytes_to_mnemonic(ent)
                seed = mnemonic_to_seed(mnemonic)
                key = AugSchemeMPL.key_gen(seed)
                if key.get_g1() == pk:
                    return (key, ent)
            index += 1
            pkent = self._get_pk_and_entropy(get_private_key_user(self.user, index))
        return None

    def get_private_key_by_fingerprint(self, fingerprint: int) -> Optional[Tuple[PrivateKey, bytes]]:
        """
        Return first private key which have the given public key fingerprint.
        """
        index = 0
        pkent = self._get_pk_and_entropy(get_private_key_user(self.user, index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                mnemonic = bytes_to_mnemonic(ent)
                seed = mnemonic_to_seed(mnemonic)
                key = AugSchemeMPL.key_gen(seed)
                if pk.get_fingerprint() == fingerprint:
                    return (key, ent)
            index += 1
            pkent = self._get_pk_and_entropy(get_private_key_user(self.user, index))
        return None

    def get_all_private_keys(self) -> List[Tuple[PrivateKey, bytes]]:
        """
        Returns all private keys which can be retrieved, with the given passphrases.
        A tuple of key, and entropy bytes (i.e. mnemonic) is returned for each key.
        """
        all_keys: List[Tuple[PrivateKey, bytes]] = []

        index = 0
        pkent = self._get_pk_and_entropy(get_private_key_user(self.user, index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                mnemonic = bytes_to_mnemonic(ent)
                seed = mnemonic_to_seed(mnemonic)
                key = AugSchemeMPL.key_gen(seed)
                if key.get_g1() == pk:
                    all_keys.append((key, ent))
            index += 1
            pkent = self._get_pk_and_entropy(get_private_key_user(self.user, index))
        return all_keys

    def get_all_public_keys(self) -> List[G1Element]:
        """
        Returns all public keys.
        """
        return [key_data[0].get_g1() for key_data in self.get_all_private_keys()]

    def get_first_public_key(self) -> Optional[G1Element]:
        """
        Returns the first public key.
        """
        key_data = self.get_first_private_key()
        return None if key_data is None else key_data[0].get_g1()

    def delete_key_by_fingerprint(self, fingerprint: int) -> int:
        """
        Deletes all keys which have the given public key fingerprint and returns how many keys were removed.
        """
        removed = 0
        for index in range(MAX_KEYS + 1):
            pkent = self._get_pk_and_entropy(get_private_key_user(self.user, index))
            if pkent is not None:
                pk, ent = pkent
                if pk.get_fingerprint() == fingerprint:
                    try:
                        self.keyring_wrapper.delete_passphrase(self.service, get_private_key_user(self.user, index))
                        removed += 1
                    except Exception:
                        pass
        return removed

    def delete_keys(self, keys_to_delete: List[Tuple[PrivateKey, bytes]]):
        """
        Deletes all keys in the list.
        """
        remaining_fingerprints = {x[0].get_g1().get_fingerprint() for x in keys_to_delete}
        remaining_removals = len(remaining_fingerprints)
        while len(remaining_fingerprints):
            key_to_delete = remaining_fingerprints.pop()
            if self.delete_key_by_fingerprint(key_to_delete) > 0:
                remaining_removals -= 1
        if remaining_removals > 0:
            raise ValueError(f"{remaining_removals} keys could not be found for deletion")

    def delete_all_keys(self) -> None:
        """
        Deletes all keys from the keychain.
        """
        for index in range(MAX_KEYS + 1):
            try:
                self.keyring_wrapper.delete_passphrase(self.service, get_private_key_user(self.user, index))
            except Exception:
                # Some platforms might throw on no existing key
                pass

    @staticmethod
    def is_keyring_locked() -> bool:
        """
        Returns whether the keyring is in a locked state. If the keyring doesn't have a master passphrase set,
        or if a master passphrase is set and the cached passphrase is valid, the keyring is "unlocked"
        """
        # Unlocked: If a master passphrase isn't set, or if the cached passphrase is valid
        if not Keychain.has_master_passphrase() or (
            Keychain.has_cached_passphrase()
            and Keychain.master_passphrase_is_valid(Keychain.get_cached_master_passphrase())
        ):
            return False

        # Locked: Everything else
        return True

    @staticmethod
    def needs_migration() -> bool:
        """
        Returns a bool indicating whether the underlying keyring needs to be migrated to the new
        format for passphrase support.
        """
        return KeyringWrapper.get_shared_instance().using_legacy_keyring()

    @staticmethod
    def handle_migration_completed():
        """
        When migration completes outside of the current process, we rely on a notification to inform
        the current process that it needs to reset/refresh its keyring. This allows us to stop using
        the legacy keyring in an already-running daemon if migration is completed using the CLI.
        """
        KeyringWrapper.get_shared_instance().refresh_keyrings()

    @staticmethod
    def migrate_legacy_keyring(
        passphrase: Optional[str] = None,
        passphrase_hint: Optional[str] = None,
        save_passphrase: bool = False,
        cleanup_legacy_keyring: bool = False,
    ) -> None:
        """
        Begins legacy keyring migration in a non-interactive manner
        """
        if passphrase is not None and passphrase != "":
            KeyringWrapper.get_shared_instance().set_master_passphrase(
                current_passphrase=None,
                new_passphrase=passphrase,
                write_to_keyring=False,
                passphrase_hint=passphrase_hint,
                save_passphrase=save_passphrase,
            )

        KeyringWrapper.get_shared_instance().migrate_legacy_keyring(cleanup_legacy_keyring=cleanup_legacy_keyring)

    @staticmethod
    def passphrase_is_optional() -> bool:
        """
        Returns whether a user-supplied passphrase is optional, as specified by the passphrase requirements.
        """
        return passphrase_requirements().get("is_optional", False)

    @staticmethod
    def minimum_passphrase_length() -> int:
        """
        Returns the minimum passphrase length, as specified by the passphrase requirements.
        """
        return passphrase_requirements().get("min_length", 0)

    @staticmethod
    def passphrase_meets_requirements(passphrase: Optional[str]) -> bool:
        """
        Returns whether the provided passphrase satisfies the passphrase requirements.
        """
        # Passphrase is not required and None was provided
        if (passphrase is None or passphrase == "") and Keychain.passphrase_is_optional():
            return True

        # Passphrase meets the minimum length requirement
        if passphrase is not None and len(passphrase) >= Keychain.minimum_passphrase_length():
            return True

        return False

    @staticmethod
    def has_master_passphrase() -> bool:
        """
        Returns a bool indicating whether the underlying keyring data
        is secured by a passphrase.
        """
        return KeyringWrapper.get_shared_instance().has_master_passphrase()

    @staticmethod
    def master_passphrase_is_valid(passphrase: str, force_reload: bool = False) -> bool:
        """
        Checks whether the provided passphrase can unlock the keyring. If force_reload
        is true, the keyring payload will be re-read from the backing file. If false,
        the passphrase will be checked against the in-memory payload.
        """
        return KeyringWrapper.get_shared_instance().master_passphrase_is_valid(passphrase, force_reload=force_reload)

    @staticmethod
    def has_cached_passphrase() -> bool:
        """
        Returns whether the master passphrase has been cached (it may need to be validated)
        """
        return KeyringWrapper.get_shared_instance().has_cached_master_passphrase()

    @staticmethod
    def get_cached_master_passphrase() -> str:
        """
        Returns the cached master passphrase
        """
        passphrase, _ = KeyringWrapper.get_shared_instance().get_cached_master_passphrase()
        return passphrase

    @staticmethod
    def set_cached_master_passphrase(passphrase: Optional[str]) -> None:
        """
        Caches the provided master passphrase
        """
        KeyringWrapper.get_shared_instance().set_cached_master_passphrase(passphrase)

    @staticmethod
    def set_master_passphrase(
        current_passphrase: Optional[str],
        new_passphrase: str,
        *,
        passphrase_hint: Optional[str] = None,
        save_passphrase: bool = False,
    ) -> None:
        """
        Encrypts the keyring contents to new passphrase, provided that the current
        passphrase can decrypt the contents
        """
        KeyringWrapper.get_shared_instance().set_master_passphrase(
            current_passphrase,
            new_passphrase,
            passphrase_hint=passphrase_hint,
            save_passphrase=save_passphrase,
        )

    @staticmethod
    def remove_master_passphrase(current_passphrase: Optional[str]) -> None:
        """
        Removes the user-provided master passphrase, and replaces it with the default
        master passphrase. The keyring contents will remain encrypted, but to the
        default passphrase.
        """
        KeyringWrapper.get_shared_instance().remove_master_passphrase(current_passphrase)

    @staticmethod
    def get_master_passphrase_hint() -> Optional[str]:
        """
        Returns the passphrase hint from the keyring
        """
        return KeyringWrapper.get_shared_instance().get_master_passphrase_hint()

    @staticmethod
    def set_master_passphrase_hint(current_passphrase: str, passphrase_hint: Optional[str]) -> None:
        """
        Convenience method for setting/removing the passphrase hint. Requires the current
        passphrase, as the passphrase hint is written as part of a passphrase update.
        """
        Keychain.set_master_passphrase(current_passphrase, current_passphrase, passphrase_hint=passphrase_hint)
