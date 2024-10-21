from __future__ import annotations

import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from hashlib import pbkdf2_hmac
from pathlib import Path
from typing import Any, Literal, Optional, TypeVar, Union, overload

import importlib_resources
from bitstring import BitArray
from chia_rs import AugSchemeMPL, G1Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32
from typing_extensions import final

from chia.util.bech32m import bech32_decode, convertbits
from chia.util.byte_types import hexstr_to_bytes
from chia.util.errors import (
    KeychainException,
    KeychainFingerprintExists,
    KeychainFingerprintNotFound,
    KeychainKeyDataMismatch,
    KeychainNotSet,
    KeychainSecretsMissing,
    KeychainUserNotFound,
)
from chia.util.file_keyring import Key
from chia.util.hash import std_hash
from chia.util.key_types import Secp256r1PrivateKey, Secp256r1PublicKey
from chia.util.keyring_wrapper import KeyringWrapper
from chia.util.observation_root import ObservationRoot
from chia.util.secret_info import SecretInfo
from chia.util.streamable import Streamable, streamable
from chia.wallet.vault.vault_root import VaultRoot

CURRENT_KEY_VERSION = "1.8"
DEFAULT_USER = f"user-chia-{CURRENT_KEY_VERSION}"  # e.g. user-chia-1.8
DEFAULT_SERVICE = f"chia-{DEFAULT_USER}"  # e.g. chia-user-chia-1.8
MAX_KEYS = 101
MIN_PASSPHRASE_LEN = 8


_T_ObservationRoot = TypeVar("_T_ObservationRoot", bound=ObservationRoot)


def supports_os_passphrase_storage() -> bool:
    return sys.platform in ["darwin", "win32", "cygwin"]


def passphrase_requirements() -> dict[str, Any]:
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
    word_list_path = importlib_resources.files(__name__.rpartition(".")[0]).joinpath("english.txt")
    contents: str = word_list_path.read_text(encoding="utf-8")
    return contents


def generate_mnemonic() -> str:
    mnemonic_bytes = bytes32.secret()
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


def check_mnemonic_validity(mnemonic_str: str) -> bool:
    mnemonic: list[str] = mnemonic_str.split(" ")
    return len(mnemonic) in [12, 15, 18, 21, 24]


def mnemonic_from_short_words(mnemonic_str: str) -> str:
    """
    Since the first 4 letters of each word is unique (or the full word, if less than 4 characters), and its common
    practice to only store the first 4 letters of each word in many offline storage solutions, also support looking
    up words by the first 4 characters
    """
    mnemonic: list[str] = mnemonic_str.split(" ")
    if len(mnemonic) not in [12, 15, 18, 21, 24]:
        raise ValueError("Invalid mnemonic length")

    four_char_dict = {word[:4]: word for word in bip39_word_list().splitlines()}
    full_words: list[str] = []
    for word in mnemonic:
        full_word = four_char_dict.get(word[:4])
        if full_word is None:
            raise ValueError(f"{word!r} is not in the mnemonic dictionary; may be misspelled")
        full_words.append(full_word)

    return " ".join(full_words)


def bytes_from_mnemonic(mnemonic_str: str) -> bytes:
    full_mnemonic_str = mnemonic_from_short_words(mnemonic_str)
    mnemonic: list[str] = full_mnemonic_str.split(" ")

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

    # mypy doesn't seem to understand the `property()` call used not as a decorator
    entropy_bytes: bytes = bit_array[:ENT].bytes
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
    # If there are only ASCII characters (as typically expected in a seed phrase), we can check if its just shortened
    # 4 letter versions of each word
    if not any(ord(c) >= 128 for c in mnemonic):
        mnemonic = mnemonic_from_short_words(mnemonic)
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


class KeyTypes(str, Enum):
    G1_ELEMENT = "G1 Element"
    VAULT_LAUNCHER = "Vault Launcher"
    SECP_256_R1 = "SECP256r1"

    @classmethod
    def parse_observation_root(cls: type[KeyTypes], pk_bytes: bytes, key_type: KeyTypes) -> ObservationRoot:
        if key_type == cls.G1_ELEMENT:
            return G1Element.from_bytes(pk_bytes)
        if key_type == cls.VAULT_LAUNCHER:
            return VaultRoot(pk_bytes)
        elif key_type == cls.SECP_256_R1:
            return Secp256r1PublicKey.from_bytes(pk_bytes)
        else:  # pragma: no cover
            # mypy should prevent this from ever running
            raise RuntimeError("Not all key types have been handled in KeyTypes.parse_observation_root")

    @classmethod
    def parse_secret_info(cls: type[KeyTypes], sk_bytes: bytes, key_type: KeyTypes) -> SecretInfo[Any]:
        if key_type == cls.G1_ELEMENT:
            return PrivateKey.from_bytes(sk_bytes)
        elif key_type == cls.SECP_256_R1:
            return Secp256r1PrivateKey.from_bytes(sk_bytes)
        else:  # pragma: no cover
            # mypy should prevent this from ever running
            raise RuntimeError("Not all key types have been handled in KeyTypes.parse_secret_info")

    @classmethod
    def parse_secret_info_from_seed(cls: type[KeyTypes], seed: bytes, key_type: KeyTypes) -> SecretInfo[Any]:
        if key_type == cls.G1_ELEMENT:
            return PrivateKey.from_seed(seed)
        elif key_type == cls.SECP_256_R1:
            return Secp256r1PrivateKey.from_seed(seed)
        else:  # pragma: no cover
            # mypy should prevent this from ever running
            raise RuntimeError("Not all key types have been handled in KeyTypes.parse_secret_info_from_seed")


@final
@streamable
@dataclass(frozen=True)
class KeyDataSecrets(Streamable):
    mnemonic: list[str]
    entropy: bytes
    secret_info_bytes: bytes
    key_type: str = KeyTypes.G1_ELEMENT.value

    @property
    def private_key(self) -> SecretInfo[Any]:
        return PUBLIC_TYPES_TO_PRIVATE_TYPES[KEY_TYPES_TO_TYPES[KeyTypes(self.key_type)]].from_bytes(
            self.secret_info_bytes
        )

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
        if (
            PUBLIC_TYPES_TO_PRIVATE_TYPES[KEY_TYPES_TO_TYPES[KeyTypes(self.key_type)]].from_seed(
                mnemonic_to_seed(mnemonic_str)
            )
            != self.private_key
        ):
            raise KeychainKeyDataMismatch("private_key")

    @classmethod
    def from_mnemonic(cls, mnemonic: str, key_type: KeyTypes = KeyTypes.G1_ELEMENT) -> KeyDataSecrets:
        return cls(
            mnemonic=mnemonic.split(),
            entropy=bytes_from_mnemonic(mnemonic),
            secret_info_bytes=bytes(
                PUBLIC_TYPES_TO_PRIVATE_TYPES[KEY_TYPES_TO_TYPES[key_type]].from_seed(mnemonic_to_seed(mnemonic))
            ),
            key_type=key_type.value,
        )

    @classmethod
    def from_entropy(cls, entropy: bytes) -> KeyDataSecrets:
        return cls.from_mnemonic(bytes_to_mnemonic(entropy))

    @classmethod
    def generate(cls) -> KeyDataSecrets:
        return cls.from_mnemonic(generate_mnemonic())

    def mnemonic_str(self) -> str:
        return " ".join(self.mnemonic)


TYPES_TO_KEY_TYPES: dict[type[ObservationRoot], KeyTypes] = {
    G1Element: KeyTypes.G1_ELEMENT,
    VaultRoot: KeyTypes.VAULT_LAUNCHER,
    Secp256r1PublicKey: KeyTypes.SECP_256_R1,
}
KEY_TYPES_TO_TYPES: dict[KeyTypes, type[ObservationRoot]] = {v: k for k, v in TYPES_TO_KEY_TYPES.items()}
PUBLIC_TYPES_TO_PRIVATE_TYPES: dict[type[ObservationRoot], type[SecretInfo[Any]]] = {
    G1Element: PrivateKey,
    Secp256r1PublicKey: Secp256r1PrivateKey,
}


@final
@streamable
@dataclass(frozen=True)
class KeyData(Streamable):
    fingerprint: uint32
    public_key: bytes
    label: Optional[str]
    secrets: Optional[KeyDataSecrets]
    key_type: str

    @cached_property
    def observation_root(self) -> ObservationRoot:
        return KeyTypes.parse_observation_root(self.public_key, KeyTypes(self.key_type))

    def __post_init__(self) -> None:
        # This is redundant if `from_*` methods are used but its to make sure there can't be an `KeyData` instance with
        # an attribute mismatch for calculated cached values. Should be ok since we don't handle a lot of keys here.
        if self.secrets is not None and self.observation_root != self.private_key.public_key():
            raise KeychainKeyDataMismatch("public_key")
        if uint32(self.observation_root.get_fingerprint()) != self.fingerprint:
            raise KeychainKeyDataMismatch("fingerprint")

    @classmethod
    def from_mnemonic(cls, mnemonic: str, label: Optional[str] = None) -> KeyData:
        private_key = AugSchemeMPL.key_gen(mnemonic_to_seed(mnemonic))
        return cls(
            fingerprint=uint32(private_key.get_g1().get_fingerprint()),
            public_key=bytes(private_key.get_g1()),
            label=label,
            secrets=KeyDataSecrets.from_mnemonic(mnemonic),
            key_type=KeyTypes.G1_ELEMENT.value,
        )

    @classmethod
    def from_entropy(cls, entropy: bytes, label: Optional[str] = None) -> KeyData:
        return cls.from_mnemonic(bytes_to_mnemonic(entropy), label)

    @classmethod
    def generate(cls, label: Optional[str] = None) -> KeyData:
        return cls.from_mnemonic(generate_mnemonic(), label)

    @property
    def mnemonic(self) -> list[str]:
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
    def private_key(self) -> SecretInfo[Any]:
        if self.secrets is None:
            raise KeychainSecretsMissing()
        return self.secrets.private_key


class Keychain:
    """
    The keychain stores two types of keys: private keys, which are SecretInfos,
    and private key seeds, which are bytes objects that are used as a seed to construct
    SecretInfos. Private key seeds are converted to mnemonics when shown to users.

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

    def _get_key_data(self, index: int, include_secrets: bool = True) -> Optional[KeyData]:
        """
        Returns the parsed keychain contents for a specific 'user' (key index). The content
        is represented by the class `KeyData`.
        """
        user = get_private_key_user(self.user, index)
        key = self.keyring_wrapper.keyring.get_key(self.service, user)
        if key is None or len(key.secret) == 0:
            raise KeychainUserNotFound(self.service, user)
        str_bytes = key.secret

        if key.metadata is None or key.metadata.get("type", KeyTypes.G1_ELEMENT.value) == KeyTypes.G1_ELEMENT.value:
            pk_bytes: bytes = str_bytes[: G1Element.SIZE]
            observation_root: ObservationRoot = G1Element.from_bytes(pk_bytes)
            fingerprint = observation_root.get_fingerprint()
            if len(str_bytes) > G1Element.SIZE:
                entropy = str_bytes[G1Element.SIZE : G1Element.SIZE + 32]
            else:
                entropy = None

            return KeyData(
                fingerprint=uint32(fingerprint),
                public_key=pk_bytes,
                label=self.keyring_wrapper.keyring.get_label(fingerprint),
                secrets=KeyDataSecrets.from_entropy(entropy) if include_secrets and entropy is not None else None,
                key_type=KeyTypes.G1_ELEMENT.value,
            )
        elif key.metadata.get("type", KeyTypes.G1_ELEMENT.value) == KeyTypes.VAULT_LAUNCHER.value:
            observation_root = VaultRoot.from_bytes(str_bytes)
            fingerprint = observation_root.get_fingerprint()
            return KeyData(
                fingerprint=uint32(fingerprint),
                public_key=str_bytes,
                label=self.keyring_wrapper.keyring.get_label(fingerprint),
                secrets=None,
                key_type=KeyTypes.VAULT_LAUNCHER.value,
            )
        else:
            return None

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

    # pylint requires these NotImplementedErrors for some reason
    @overload
    def add_key(self, mnemonic_or_pk: str) -> tuple[SecretInfo[Any], KeyTypes]:
        raise NotImplementedError()  # pragma: no cover

    @overload
    def add_key(self, mnemonic_or_pk: str, label: Optional[str]) -> tuple[SecretInfo[Any], KeyTypes]:
        raise NotImplementedError()  # pragma: no cover

    @overload
    def add_key(self, mnemonic_or_pk: str, *, key_type: KeyTypes) -> tuple[SecretInfo[Any], KeyTypes]:
        raise NotImplementedError()  # pragma: no cover

    @overload
    def add_key(
        self, mnemonic_or_pk: str, label: Optional[str], private: Literal[True]
    ) -> tuple[SecretInfo[Any], KeyTypes]:
        raise NotImplementedError()  # pragma: no cover

    @overload
    def add_key(
        self, mnemonic_or_pk: str, label: Optional[str], private: Literal[False]
    ) -> tuple[ObservationRoot, KeyTypes]:
        raise NotImplementedError()  # pragma: no cover

    @overload
    def add_key(
        self, mnemonic_or_pk: str, label: Optional[str], private: bool
    ) -> tuple[Union[SecretInfo[Any], ObservationRoot], KeyTypes]:
        raise NotImplementedError()  # pragma: no cover

    @overload
    def add_key(
        self, mnemonic_or_pk: str, label: Optional[str], private: Literal[True], key_type: KeyTypes
    ) -> tuple[SecretInfo[Any], KeyTypes]:
        raise NotImplementedError()  # pragma: no cover

    @overload
    def add_key(
        self, mnemonic_or_pk: str, label: Optional[str], private: Literal[False], key_type: KeyTypes
    ) -> tuple[ObservationRoot, KeyTypes]:
        raise NotImplementedError()  # pragma: no cover

    @overload
    def add_key(
        self, mnemonic_or_pk: str, label: Optional[str], private: bool, key_type: KeyTypes
    ) -> tuple[Union[SecretInfo[Any], ObservationRoot], KeyTypes]:
        raise NotImplementedError()  # pragma: no cover

    def add_key(
        self,
        mnemonic_or_pk: str,
        label: Optional[str] = None,
        private: bool = True,
        key_type: KeyTypes = KeyTypes.G1_ELEMENT,
    ) -> tuple[Union[SecretInfo[Any], ObservationRoot], KeyTypes]:
        """
        Adds a key to the keychain. The keychain itself will store the public key, and the entropy bytes (if given),
        but not the passphrase.
        """
        key: Union[SecretInfo[Any], ObservationRoot]
        if private:
            seed = mnemonic_to_seed(mnemonic_or_pk)
            entropy = bytes_from_mnemonic(mnemonic_or_pk)
            index = self._get_free_private_key_index()
            key = KeyTypes.parse_secret_info_from_seed(seed, key_type)
            pk = key.public_key()
            key_data = Key(bytes(pk) + entropy, metadata={"type": key_type.value})
            fingerprint = pk.get_fingerprint()
        else:
            index = self._get_free_private_key_index()
            if mnemonic_or_pk.startswith("bls1238"):
                _, data = bech32_decode(mnemonic_or_pk, max_length=94)
                assert data is not None
                pk_bytes = bytes(convertbits(data, 5, 8, False))
            else:
                pk_bytes = hexstr_to_bytes(mnemonic_or_pk)
            key = KeyTypes.parse_observation_root(pk_bytes, key_type)
            key_data = Key(pk_bytes, metadata={"type": key_type.value})
            fingerprint = key.get_fingerprint()

        if fingerprint in [pk.get_fingerprint() for pk in self.get_all_public_keys()]:
            # Prevents duplicate add
            raise KeychainFingerprintExists(fingerprint)

        # Try to set the label first, it may fail if the label is invalid or already exists.
        # This can probably just be moved into `FileKeyring.set_passphrase` after the legacy keyring stuff was dropped.
        if label is not None:
            self.keyring_wrapper.keyring.set_label(fingerprint, label)

        try:
            self.keyring_wrapper.keyring.set_key(
                self.service,
                get_private_key_user(self.user, index),
                key_data,
            )
        except Exception:
            if label is not None:
                self.keyring_wrapper.keyring.delete_label(fingerprint)
            raise

        return key, key_type

    def set_label(self, fingerprint: int, label: str) -> None:
        """
        Assigns the given label to the first key with the given fingerprint.
        """
        self.get_key(fingerprint)  # raise if the fingerprint doesn't exist
        self.keyring_wrapper.keyring.set_label(fingerprint, label)

    def delete_label(self, fingerprint: int) -> None:
        """
        Removes the label assigned to the key with the given fingerprint.
        """
        self.keyring_wrapper.keyring.delete_label(fingerprint)

    def _iterate_through_key_datas(
        self, include_secrets: bool = True, skip_public_only: bool = False
    ) -> Iterator[KeyData]:
        for index in range(MAX_KEYS):
            try:
                key_data = self._get_key_data(index, include_secrets=include_secrets)
                if key_data is None or (skip_public_only and key_data.secrets is None):
                    continue
                yield key_data
            except KeychainUserNotFound:
                pass
        return None

    def get_first_private_key(self, key_type: Optional[KeyTypes] = None) -> Optional[tuple[SecretInfo[Any], bytes]]:
        """
        Returns the first key in the keychain that has one of the passed in passphrases.
        """
        for key_data in self._iterate_through_key_datas(skip_public_only=True):
            if key_type is not None and key_data.key_type != key_type.value:
                continue
            return key_data.private_key, key_data.entropy
        return None

    def get_private_key_by_fingerprint(self, fingerprint: int) -> Optional[tuple[SecretInfo[Any], bytes]]:
        """
        Return first private key which have the given public key fingerprint.
        """
        for key_data in self._iterate_through_key_datas(skip_public_only=True):
            if key_data.fingerprint == fingerprint:
                return key_data.private_key, key_data.entropy
        return None

    def get_all_private_keys(self) -> list[tuple[SecretInfo[Any], bytes]]:
        """
        Returns all private keys which can be retrieved, with the given passphrases.
        A tuple of key, and entropy bytes (i.e. mnemonic) is returned for each key.
        """
        all_keys: list[tuple[SecretInfo[Any], bytes]] = []
        for key_data in self._iterate_through_key_datas(skip_public_only=True):
            all_keys.append((key_data.private_key, key_data.entropy))
        return all_keys

    def get_key(self, fingerprint: int, include_secrets: bool = False) -> KeyData:
        """
        Return the KeyData of the first key which has the given public key fingerprint.
        """
        for key_data in self._iterate_through_key_datas(include_secrets=include_secrets, skip_public_only=False):
            if key_data.observation_root.get_fingerprint() == fingerprint:
                return key_data
        raise KeychainFingerprintNotFound(fingerprint)

    def get_keys(self, include_secrets: bool = False) -> list[KeyData]:
        """
        Returns the KeyData of all keys which can be retrieved.
        """
        all_keys: list[KeyData] = []
        for key_data in self._iterate_through_key_datas(include_secrets=include_secrets, skip_public_only=False):
            all_keys.append(key_data)

        return all_keys

    def get_all_public_keys(self) -> list[ObservationRoot]:
        """
        Returns all public keys.
        """
        all_keys: list[ObservationRoot] = []
        for key_data in self._iterate_through_key_datas(skip_public_only=False):
            all_keys.append(key_data.observation_root)

        return all_keys

    def get_all_public_keys_of_type(self, key_type: type[_T_ObservationRoot]) -> list[_T_ObservationRoot]:
        all_keys: list[_T_ObservationRoot] = []
        for key_data in self._iterate_through_key_datas(skip_public_only=False):
            if key_data.key_type == TYPES_TO_KEY_TYPES[key_type]:
                assert isinstance(key_data.observation_root, key_type)
                all_keys.append(key_data.observation_root)

        return all_keys

    def get_first_public_key(self) -> Optional[G1Element]:
        """
        Returns the first public key.
        """
        key_data = self.get_first_private_key()
        return None if key_data is None else key_data[0].public_key()

    def delete_key_by_fingerprint(self, fingerprint: int) -> int:
        """
        Deletes all keys which have the given public key fingerprint and returns how many keys were removed.
        """
        removed = 0
        # We duplicate ._iterate_through_key_datas due to needing the index
        for index in range(MAX_KEYS):
            try:
                key_data = self._get_key_data(index, include_secrets=False)
                if key_data is not None and key_data.fingerprint == fingerprint:
                    try:
                        self.keyring_wrapper.keyring.delete_label(key_data.fingerprint)
                    except (KeychainException, NotImplementedError):
                        # Just try to delete the label and move on if there wasn't one
                        pass
                    try:
                        self.keyring_wrapper.keyring.delete_key(self.service, get_private_key_user(self.user, index))
                        removed += 1
                    except Exception:
                        pass
            except KeychainUserNotFound:
                pass
        return removed

    def delete_all_keys(self) -> None:
        """
        Deletes all keys from the keychain.
        """
        for key_data in self._iterate_through_key_datas(include_secrets=False, skip_public_only=False):
            self.delete_key_by_fingerprint(key_data.fingerprint)

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
        return passphrase_requirements().get("is_optional", False)  # type: ignore[no-any-return]

    @staticmethod
    def minimum_passphrase_length() -> int:
        """
        Returns the minimum passphrase length, as specified by the passphrase requirements.
        """
        return passphrase_requirements().get("min_length", 0)  # type: ignore[no-any-return]

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
