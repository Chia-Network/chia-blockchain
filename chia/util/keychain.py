from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass
from hashlib import pbkdf2_hmac
from pathlib import Path
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Tuple

import pkg_resources
from bitstring import BitArray  # pyright: reportMissingImports=false
from blspy import AugSchemeMPL, G1Element, PrivateKey  # pyright: reportMissingImports=false
from typing_extensions import final

from chia.util.errors import (
    KeychainException,
    KeychainFingerprintExists,
    KeychainFingerprintNotFound,
    KeychainKeyDataMismatch,
    KeychainNotSet,
    KeychainSecretsMissing,
    KeychainUserNotFound,
)
from chia.util.hash import std_hash
from chia.util.ints import uint32
from chia.util.keyring_wrapper import KeyringWrapper
from chia.util.streamable import Streamable, streamable

CURRENT_KEY_VERSION = "1.8"
DEFAULT_USER = f"user-chia-{CURRENT_KEY_VERSION}"  # e.g. user-chia-1.8
DEFAULT_SERVICE = f"chia-{DEFAULT_USER}"  # e.g. chia-user-chia-1.8
MAX_KEYS = 100
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


@final
@streamable
@dataclass(frozen=True)
class KeyDataSecrets(Streamable):
    mnemonic: List[str]
    entropy: bytes
    private_key: PrivateKey

    def __post_init__(self) -> None:
        # This is redundant if `from_*` methods are used but its to make sure there can't be an `KeyDataSecrets`
        # instance with an attribute mismatch for calculated cached values. Should be ok since we don't handle a lot of
        # keys here.
        mnemonic_str = self.mnemonic_str()
        try:
            bytes_from_mnemonic(mnemonic_str)
        except Exception as e:
            raise KeychainKeyDataMismatch("mnemonic") from e
        if bytes_from_mnemonic(mnemonic_str) != self.entropy:
            raise KeychainKeyDataMismatch("entropy")
        if AugSchemeMPL.key_gen(mnemonic_to_seed(mnemonic_str)) != self.private_key:
            raise KeychainKeyDataMismatch("private_key")

    @classmethod
    def from_mnemonic(cls, mnemonic: str) -> KeyDataSecrets:
        return cls(
            mnemonic=mnemonic.split(),
            entropy=bytes_from_mnemonic(mnemonic),
            private_key=AugSchemeMPL.key_gen(mnemonic_to_seed(mnemonic)),
        )

    @classmethod
    def from_entropy(cls, entropy: bytes) -> KeyDataSecrets:
        return cls.from_mnemonic(bytes_to_mnemonic(entropy))

    @classmethod
    def generate(cls) -> KeyDataSecrets:
        return cls.from_mnemonic(generate_mnemonic())

    def mnemonic_str(self) -> str:
        return " ".join(self.mnemonic)


@final
@streamable
@dataclass(frozen=True)
class KeyData(Streamable):
    fingerprint: uint32
    public_key: G1Element
    label: Optional[str]
    secrets: Optional[KeyDataSecrets]

    def __post_init__(self) -> None:
        # This is redundant if `from_*` methods are used but its to make sure there can't be an `KeyData` instance with
        # an attribute mismatch for calculated cached values. Should be ok since we don't handle a lot of keys here.
        if self.secrets is not None and self.public_key != self.private_key.get_g1():
            raise KeychainKeyDataMismatch("public_key")
        if self.public_key.get_fingerprint() != self.fingerprint:
            raise KeychainKeyDataMismatch("fingerprint")

    @classmethod
    def from_mnemonic(cls, mnemonic: str, label: Optional[str] = None) -> KeyData:
        private_key = AugSchemeMPL.key_gen(mnemonic_to_seed(mnemonic))
        return cls(
            fingerprint=private_key.get_g1().get_fingerprint(),
            public_key=private_key.get_g1(),
            label=label,
            secrets=KeyDataSecrets.from_mnemonic(mnemonic),
        )

    @classmethod
    def from_entropy(cls, entropy: bytes, label: Optional[str] = None) -> KeyData:
        return cls.from_mnemonic(bytes_to_mnemonic(entropy), label)

    @classmethod
    def generate(cls, label: Optional[str] = None) -> KeyData:
        return cls.from_mnemonic(generate_mnemonic(), label)

    @property
    def mnemonic(self) -> List[str]:
        if self.secrets is None:
            raise KeychainSecretsMissing()
        return self.secrets.mnemonic

    def mnemonic_str(self) -> str:
        if self.secrets is None:
            raise KeychainSecretsMissing()
        return self.secrets.mnemonic_str()

    @property
    def entropy(self) -> bytes:
        if self.secrets is None:
            raise KeychainSecretsMissing()
        return self.secrets.entropy

    @property
    def private_key(self) -> PrivateKey:
        if self.secrets is None:
            raise KeychainSecretsMissing()
        return self.secrets.private_key


class Keychain:
    """
    The keychain stores two types of keys: private keys, which are PrivateKeys from blspy,
    and private key seeds, which are bytes objects that are used as a seed to construct
    PrivateKeys. Private key seeds are converted to mnemonics when shown to users.

    Both types of keys are stored as hex strings in the python keyring, and the implementation of
    the keyring depends on OS. Both types of keys can be added, and get_private_keys returns a
    list of all keys.
    """

    def __init__(self, user: Optional[str] = None, service: Optional[str] = None):
        self.user = user if user is not None else default_keychain_user()
        self.service = service if service is not None else default_keychain_service()

        keyring_wrapper: Optional[KeyringWrapper] = KeyringWrapper.get_shared_instance()

        if keyring_wrapper is None:
            raise KeychainNotSet("KeyringWrapper not set")

        self.keyring_wrapper = keyring_wrapper

    def _get_key_data(self, index: int, include_secrets: bool = True) -> KeyData:
        """
        Returns the parsed keychain contents for a specific 'user' (key index). The content
        is represented by the class `KeyData`.
        """
        user = get_private_key_user(self.user, index)
        read_str = self.keyring_wrapper.get_passphrase(self.service, user)
        if read_str is None or len(read_str) == 0:
            raise KeychainUserNotFound(self.service, user)
        str_bytes = bytes.fromhex(read_str)

        public_key = G1Element.from_bytes(str_bytes[: G1Element.SIZE])
        fingerprint = public_key.get_fingerprint()
        entropy = str_bytes[G1Element.SIZE : G1Element.SIZE + 32]

        return KeyData(
            fingerprint=fingerprint,
            public_key=public_key,
            label=self.keyring_wrapper.get_label(fingerprint),
            secrets=KeyDataSecrets.from_entropy(entropy) if include_secrets else None,
        )

    def _get_free_private_key_index(self) -> int:
        """
        Get the index of the first free spot in the keychain.
        """
        index = 0
        while True:
            try:
                self._get_key_data(index)
                index += 1
            except KeychainUserNotFound:
                return index

    def add_private_key(self, mnemonic: str, label: Optional[str] = None) -> PrivateKey:
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

        # Try to set the label first, it may fail if the label is invalid or already exists.
        # This can probably just be moved into `FileKeyring.set_passphrase` after the legacy keyring stuff was dropped.
        if label is not None:
            self.keyring_wrapper.set_label(fingerprint, label)

        try:
            self.keyring_wrapper.set_passphrase(
                self.service,
                get_private_key_user(self.user, index),
                bytes(key.get_g1()).hex() + entropy.hex(),
            )
        except Exception:
            if label is not None:
                self.keyring_wrapper.delete_label(fingerprint)
            raise

        return key

    def set_label(self, fingerprint: int, label: str) -> None:
        """
        Assigns the given label to the first key with the given fingerprint.
        """
        self.get_key(fingerprint)  # raise if the fingerprint doesn't exist
        self.keyring_wrapper.set_label(fingerprint, label)

    def delete_label(self, fingerprint: int) -> None:
        """
        Removes the label assigned to the key with the given fingerprint.
        """
        self.keyring_wrapper.delete_label(fingerprint)

    def get_first_private_key(self) -> Optional[Tuple[PrivateKey, bytes]]:
        """
        Returns the first key in the keychain that has one of the passed in passphrases.
        """
        for index in range(MAX_KEYS + 1):
            try:
                key_data = self._get_key_data(index)
                return key_data.private_key, key_data.entropy
            except KeychainUserNotFound:
                pass
        return None

    def get_private_key_by_fingerprint(self, fingerprint: int) -> Optional[Tuple[PrivateKey, bytes]]:
        """
        Return first private key which have the given public key fingerprint.
        """
        for index in range(MAX_KEYS + 1):
            try:
                key_data = self._get_key_data(index)
                if key_data.fingerprint == fingerprint:
                    return key_data.private_key, key_data.entropy
            except KeychainUserNotFound:
                pass
        return None

    def get_all_private_keys(self) -> List[Tuple[PrivateKey, bytes]]:
        """
        Returns all private keys which can be retrieved, with the given passphrases.
        A tuple of key, and entropy bytes (i.e. mnemonic) is returned for each key.
        """
        all_keys: List[Tuple[PrivateKey, bytes]] = []
        for index in range(MAX_KEYS + 1):
            try:
                key_data = self._get_key_data(index)
                all_keys.append((key_data.private_key, key_data.entropy))
            except KeychainUserNotFound:
                pass
        return all_keys

    def get_key(self, fingerprint: int, include_secrets: bool = False) -> KeyData:
        """
        Return the KeyData of the first key which has the given public key fingerprint.
        """
        for index in range(MAX_KEYS + 1):
            try:
                key_data = self._get_key_data(index, include_secrets)
                if key_data.public_key.get_fingerprint() == fingerprint:
                    return key_data
            except KeychainUserNotFound:
                pass
        raise KeychainFingerprintNotFound(fingerprint)

    def get_keys(self, include_secrets: bool = False) -> List[KeyData]:
        """
        Returns the KeyData of all keys which can be retrieved.
        """
        all_keys: List[KeyData] = []
        for index in range(MAX_KEYS + 1):
            try:
                key_data = self._get_key_data(index, include_secrets)
                all_keys.append(key_data)
            except KeychainUserNotFound:
                pass
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
            try:
                key_data = self._get_key_data(index, include_secrets=False)
                if key_data.fingerprint == fingerprint:
                    try:
                        self.keyring_wrapper.delete_label(key_data.fingerprint)
                    except (KeychainException, NotImplementedError):
                        # Just try to delete the label and move on if there wasn't one
                        pass
                    try:
                        self.keyring_wrapper.delete_passphrase(self.service, get_private_key_user(self.user, index))
                        removed += 1
                    except Exception:
                        pass
            except KeychainUserNotFound:
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
                key_data = self._get_key_data(index)
                self.delete_key_by_fingerprint(key_data.fingerprint)
            except KeychainUserNotFound:
                pass

    @staticmethod
    def is_keyring_locked() -> bool:
        """
        Returns whether the keyring is in a locked state. If the keyring doesn't have a master passphrase set,
        or if a master passphrase is set and the cached passphrase is valid, the keyring is "unlocked"
        """
        # Unlocked: If a master passphrase isn't set, or if the cached passphrase is valid
        if not Keychain.has_master_passphrase():
            return False

        passphrase = Keychain.get_cached_master_passphrase()
        if passphrase is None:
            return True

        if Keychain.master_passphrase_is_valid(passphrase):
            return False

        # Locked: Everything else
        return True

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
    def get_cached_master_passphrase() -> Optional[str]:
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
