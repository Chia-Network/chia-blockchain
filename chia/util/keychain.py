import unicodedata

# from functools import wraps
from getpass import getpass
from hashlib import pbkdf2_hmac
from secrets import token_bytes
from sys import platform
from time import sleep
from typing import List, Optional, Tuple

import keyring as keyring_main
import pkg_resources
from bitstring import BitArray
from blspy import AugSchemeMPL, G1Element, PrivateKey
from keyrings.cryptfile.cryptfile import CryptFileKeyring

from chia.util.hash import std_hash


FAILED_ATTEMPT_DELAY = 1
MAX_KEYS = 100
MAX_RETRIES = 3


class _KeyringWrapper:
    # Static instances
    __keyring = None
    __cached_password: Optional[str] = None

    def __init__(self):
        if _KeyringWrapper.__keyring:
            raise Exception("KeyringWrapper has already been instantiated")

        if platform == "win32" or platform == "cygwin":
            import keyring.backends.Windows

            keyring.set_keyring(keyring.backends.Windows.WinVaultKeyring())
        elif platform == "darwin":
            import keyring.backends.macOS

            keyring.set_keyring(keyring.backends.macOS.Keyring())
        elif platform == "linux":
            keyring = CryptFileKeyring()
            keyring.keyring_key = "your keyring password"  # type: ignore
        else:
            keyring = keyring_main

        _KeyringWrapper.__keyring = keyring

    @staticmethod
    def get_keyring():
        if not _KeyringWrapper.__keyring:
            _KeyringWrapper()

        return _KeyringWrapper.__keyring

    @staticmethod
    def get_cached_password() -> Optional[str]:
        return _KeyringWrapper.__cached_password

    @staticmethod
    def set_cached_password(password: Optional[str]) -> None:
        _KeyringWrapper.__cached_password = password

    @staticmethod
    def is_password_protected() -> bool:
        """
        Returns a bool indicating whether the underlying keyring data
        is secured by a password.
        """
        # TODO: Inspect blob
        return False

    @staticmethod
    def password_is_valid(password: Optional[str]) -> bool:
        return password == "asdfasdf"

    @staticmethod
    def set_password(current_password: Optional[str], new_password: str) -> None:
        if _KeyringWrapper.is_password_protected() and not _KeyringWrapper.password_is_valid(current_password):
            raise ValueError("invalid current password")
        # TODO: Encrypt blob
        _KeyringWrapper.set_cached_password(new_password)
        print(f"setting password: {new_password}, current_password: {current_password}")

    @staticmethod
    def remove_password(current_password: Optional[str]) -> None:
        if _KeyringWrapper.is_password_protected() and not _KeyringWrapper.password_is_valid(current_password):
            raise ValueError("invalid current password")
        print(f"removing password: current_password: {current_password}")


def obtain_current_password(prompt: str = "Password: ", use_password_cache: bool = False) -> str:
    print(f"obtain_current_password: use_password_cache: {use_password_cache}")

    if use_password_cache:
        password = _KeyringWrapper.get_cached_password()
        if password:
            if _KeyringWrapper.password_is_valid(password):
                return password
            else:
                # Cached password is bad, clear the cache
                _KeyringWrapper.set_cached_password(None)

    for i in range(MAX_RETRIES):
        password = getpass(prompt)

        if _KeyringWrapper.password_is_valid(password):
            # If using the password cache, and the user inputted a password, update the cache
            if use_password_cache:
                _KeyringWrapper.set_cached_password(password)
            return password

        sleep(FAILED_ATTEMPT_DELAY)
        print("Incorrect password\n")
    raise ValueError("maximum password attempts reached")


def unlock_keyring_if_necessary(use_password_cache=False) -> None:
    if _KeyringWrapper.is_password_protected():
        obtain_current_password(use_password_cache=use_password_cache)


def unlocks_keyring(use_password_cache=False):
    print(f"unlocks_keyring: use_password_cache: {use_password_cache}")

    def inner(func):
        """
        Decorator used to unlock the keyring interactively, if necessary
        """

        def wrapper(*args, **kwargs):
            try:
                unlock_keyring_if_necessary(use_password_cache=use_password_cache)
            except Exception:
                raise RuntimeError("Unable to unlock the keyring")
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


def mnemonic_to_seed(mnemonic: str, passphrase: str) -> bytes:
    """
    Uses BIP39 standard to derive a seed from entropy bytes.
    """
    salt_str: str = "mnemonic" + passphrase
    salt = unicodedata.normalize("NFKD", salt_str).encode("utf-8")
    mnemonic_normalized = unicodedata.normalize("NFKD", mnemonic).encode("utf-8")
    seed = pbkdf2_hmac("sha512", mnemonic_normalized, salt, 2048)

    assert len(seed) == 64
    return seed


class Keychain:
    """
    The keychain stores two types of keys: private keys, which are PrivateKeys from blspy,
    and private key seeds, which are bytes objects that are used as a seed to construct
    PrivateKeys. Private key seeds are converted to mnemonics when shown to users.

    Both types of keys are stored as hex strings in the python keyring, and the implementation of
    the keyring depends on OS. Both types of keys can be added, and get_private_keys returns a
    list of all keys.
    """

    testing: bool
    user: str

    def __init__(self, user: str = "user-chia-1.8", testing: bool = False):
        self.testing = testing
        self.user = user

    @staticmethod
    def _get_keyring():
        """
        Returns the underlying keyring wrapped by KeyringWrapper. Implementations
        differ based on the host OS.
        """
        return _KeyringWrapper.get_keyring()

    def _get_service(self) -> str:
        """
        The keychain stores keys under a different name for tests.
        """
        if self.testing:
            return f"chia-{self.user}-test"
        else:
            return f"chia-{self.user}"

    @unlocks_keyring(use_password_cache=True)
    def _get_pk_and_entropy(self, user: str) -> Optional[Tuple[G1Element, bytes]]:
        """
        Returns the keychain contents for a specific 'user' (key index). The contents
        include an G1Element and the entropy required to generate the private key.
        Note that generating the actual private key also requires the passphrase.
        """
        read_str = Keychain._get_keyring().get_password(self._get_service(), user)
        if read_str is None or len(read_str) == 0:
            return None
        str_bytes = bytes.fromhex(read_str)
        return (
            G1Element.from_bytes(str_bytes[: G1Element.SIZE]),
            str_bytes[G1Element.SIZE :],  # flake8: noqa
        )

    def _get_private_key_user(self, index: int) -> str:
        """
        Returns the keychain user string for a key index.
        """
        if self.testing:
            return f"wallet-{self.user}-test-{index}"
        else:
            return f"wallet-{self.user}-{index}"

    def _get_free_private_key_index(self) -> int:
        """
        Get the index of the first free spot in the keychain.
        """
        index = 0
        while True:
            pk = self._get_private_key_user(index)
            pkent = self._get_pk_and_entropy(pk)
            if pkent is None:
                return index
            index += 1

    def add_private_key(self, mnemonic: str, passphrase: str) -> PrivateKey:
        """
        Adds a private key to the keychain, with the given entropy and passphrase. The
        keychain itself will store the public key, and the entropy bytes,
        but not the passphrase.
        """
        seed = mnemonic_to_seed(mnemonic, passphrase)
        entropy = bytes_from_mnemonic(mnemonic)
        index = self._get_free_private_key_index()
        key = AugSchemeMPL.key_gen(seed)
        fingerprint = key.get_g1().get_fingerprint()

        if fingerprint in [pk.get_fingerprint() for pk in self.get_all_public_keys()]:
            # Prevents duplicate add
            return key

        Keychain._get_keyring().set_password(
            self._get_service(),
            self._get_private_key_user(index),
            bytes(key.get_g1()).hex() + entropy.hex(),
        )
        return key

    def get_first_private_key(self, passphrases: List[str] = [""]) -> Optional[Tuple[PrivateKey, bytes]]:
        """
        Returns the first key in the keychain that has one of the passed in passphrases.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                for pp in passphrases:
                    mnemonic = bytes_to_mnemonic(ent)
                    seed = mnemonic_to_seed(mnemonic, pp)
                    key = AugSchemeMPL.key_gen(seed)
                    if key.get_g1() == pk:
                        return (key, ent)
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        return None

    def get_private_key_by_fingerprint(
        self, fingerprint: int, passphrases: List[str] = [""]
    ) -> Optional[Tuple[PrivateKey, bytes]]:
        """
        Return first private key which have the given public key fingerprint.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                for pp in passphrases:
                    mnemonic = bytes_to_mnemonic(ent)
                    seed = mnemonic_to_seed(mnemonic, pp)
                    key = AugSchemeMPL.key_gen(seed)
                    if pk.get_fingerprint() == fingerprint:
                        return (key, ent)
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        return None

    def get_all_private_keys(self, passphrases: List[str] = [""]) -> List[Tuple[PrivateKey, bytes]]:
        """
        Returns all private keys which can be retrieved, with the given passphrases.
        A tuple of key, and entropy bytes (i.e. mnemonic) is returned for each key.
        """
        all_keys: List[Tuple[PrivateKey, bytes]] = []

        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                for pp in passphrases:
                    mnemonic = bytes_to_mnemonic(ent)
                    seed = mnemonic_to_seed(mnemonic, pp)
                    key = AugSchemeMPL.key_gen(seed)
                    if key.get_g1() == pk:
                        all_keys.append((key, ent))
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        return all_keys

    def get_all_public_keys(self) -> List[G1Element]:
        """
        Returns all public keys.
        """
        all_keys: List[Tuple[G1Element, bytes]] = []

        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                all_keys.append(pk)
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        return all_keys

    def get_first_public_key(self) -> Optional[G1Element]:
        """
        Returns the first public key.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                return pk
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        return None

    def delete_key_by_fingerprint(self, fingerprint: int):
        """
        Deletes all keys which have the given public key fingerprint.
        """

        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                if pk.get_fingerprint() == fingerprint:
                    Keychain._get_keyring().delete_password(self._get_service(), self._get_private_key_user(index))
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))

    def delete_all_keys(self):
        """
        Deletes all keys from the keychain.
        """

        index = 0
        delete_exception = False
        pkent = None
        while True:
            try:
                pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
                Keychain._get_keyring().delete_password(self._get_service(), self._get_private_key_user(index))
            except Exception:
                # Some platforms might throw on no existing key
                delete_exception = True

            # Stop when there are no more keys to delete
            if (pkent is None or delete_exception) and index > MAX_KEYS:
                break
            index += 1

        index = 0
        delete_exception = True
        pkent = None
        while True:
            try:
                pkent = self._get_pk_and_entropy(
                    self._get_private_key_user(index)
                )  # changed from _get_fingerprint_and_entropy to _get_pk_and_entropy - GH
                Keychain._get_keyring().delete_password(self._get_service(), self._get_private_key_user(index))
            except Exception:
                # Some platforms might throw on no existing key
                delete_exception = True

            # Stop when there are no more keys to delete
            if (pkent is None or delete_exception) and index > MAX_KEYS:
                break
            index += 1

    @staticmethod
    def is_password_protected() -> bool:
        """
        Returns a bool indicating whether the underlying keyring data
        is secured by a password.
        """
        return _KeyringWrapper.is_password_protected()

    @staticmethod
    def password_is_valid(password: str) -> bool:
        return _KeyringWrapper.password_is_valid(password)

    @staticmethod
    def has_cached_password() -> bool:
        password = _KeyringWrapper.get_cached_password()
        return password != None and len(password) > 0

    @staticmethod
    def set_cached_password(password: Optional[str]) -> None:
        _KeyringWrapper.set_cached_password(password)

    @staticmethod
    def set_password(current_password: Optional[str], new_password: str) -> None:
        _KeyringWrapper.set_password(current_password, new_password)

    @staticmethod
    def remove_password(current_password: Optional[str]) -> None:
        _KeyringWrapper.remove_password(current_password)
