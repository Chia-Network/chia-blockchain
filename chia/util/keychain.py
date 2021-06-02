from logging import root
from chia.util.default_root import DEFAULT_ROOT_PATH
import unicodedata

# from functools import wraps
from getpass import getpass
from hashlib import pbkdf2_hmac
from pathlib import Path
from secrets import token_bytes
from sys import platform
from time import sleep
from typing import List, Optional, Tuple

import base64
import keyring as keyring_main
import os
import pkg_resources
import shutil
import sys
import yaml

from bitstring import BitArray
from blspy import AugSchemeMPL, G1Element, PrivateKey
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from keyrings.cryptfile.cryptfile import CryptFileKeyring

from chia.util.hash import std_hash


FAILED_ATTEMPT_DELAY = 1
MAX_KEYS = 100
MAX_RETRIES = 3
SALT_BYTES = 16
NONCE_BYTES = 16
HASH_ITERS = 100000
CHECKBYTES_VALUE = b'5f365b8292ee505b'  # Randomly generated


class _FileKeyring:
    keyring_path: Path = None
    salt: List[bytes] = None
    payload: dict = None

    @staticmethod
    def keyring_path_from_root(root_path: str) -> Path:
        path_filename = Path(root_path) / "config" / "keyring.yaml"
        return path_filename

    def __init__(self, root_path: str = DEFAULT_ROOT_PATH):
        self.keyring_path = _FileKeyring.keyring_path_from_root(root_path)
        if self.has_content():
            self.load_keyring()
        else:
            self.salt = token_bytes(SALT_BYTES)
            self.payload = {}
        print(f"(TODO: remove) ***** salt: {self.salt.hex()}")

    def get_nonce(self) -> List[bytes]:
        return token_bytes(NONCE_BYTES)

    def has_content(self) -> bool:
        print("(TODO: remove) ***** has_content")
        return self.keyring_path.is_file() and self.keyring_path.stat().st_size > 0

    def get_password(self, service: str, user: str) -> str:
        print("(TODO: remove) ***** get_password")
        keys = self.payload.get("keys") or {}
        password = keys.get(user)
        return password

    def set_password(self, service: str, user: str, password_bytes: bytes):
        print("(TODO: remove) ***** set_password")
        keys = self.payload.get("keys") or {}
        password = password_bytes.hex() if type(password_bytes) == type(bytes) else str(password_bytes)
        keys[user] = password
        self.write_keyring()  # Updates the cached payload

    def delete_password(self, service:str, user: str):
        print("(TODO: remove) ***** delete_password")
        keys = self.payload.get("keys") or {}
        keys.pop(user, None)
        self.write_keyring()  # Updates the cached payload

    def get_symmetric_key(self) -> List[bytes]:
        # TODO: remove
        password = "asdfasdf".encode()  # _KeyringWrapper.get_shared_instance().get_cached_master_password().encode()
        key = pbkdf2_hmac('sha256', password, self.salt, HASH_ITERS)
        return key

    def encrypt_data(self, input_data: List[bytes], nonce: List[bytes]) -> List[bytes]:
        key = self.get_symmetric_key()
        iv = nonce
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded_data = padder.update(input_data) + padder.finalize()
        data = encryptor.update(padded_data) + encryptor.finalize()
        return data

    def decrypt_data(self, input_data: List[bytes], nonce: List[bytes]) -> List[bytes]:
        key = self.get_symmetric_key()
        iv = nonce
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted_data = decryptor.update(input_data) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        output = unpadder.update(decrypted_data) + unpadder.finalize()
        print(f"***** decrypted: {output.hex()}")
        return output

    def load_keyring(self):
        if not self.keyring_path.is_file():
            raise ValueError("Keyring file not found")

        outer_payload = dict(yaml.safe_load(open(self.keyring_path, "r")))
        version = int(outer_payload.get("version"))
        max_supported_version = 1
        if version > max_supported_version:
            print(f"Keyring format is unrecognized. Found version {version}, expected a value <= {max_supported_version}")
            sys.exit(-1)
        self.salt = bytes.fromhex(outer_payload.get("salt"))
        nonce = bytes.fromhex(outer_payload.get("nonce"))
        encrypted_payload = base64.b64decode(yaml.safe_load(outer_payload.get("data") or ""))
        decrypted_data = self.decrypt_data(encrypted_payload, nonce)
        checkbytes = decrypted_data[:len(CHECKBYTES_VALUE)]
        if not checkbytes == CHECKBYTES_VALUE:
            raise ValueError("decryption failure")
        inner_payload = decrypted_data[len(CHECKBYTES_VALUE):]

        self.payload = dict(yaml.safe_load(inner_payload))

    def write_keyring(self):
        inner_payload = self.payload
        inner_payload_yaml = yaml.safe_dump(inner_payload)
        nonce = self.get_nonce()
        encrypted_inner_payload = self.encrypt_data(CHECKBYTES_VALUE + inner_payload_yaml.encode(), nonce)
        outer_payload = {
            "version": 1,
            "salt": self.salt.hex(),
            "nonce": nonce.hex(),
            "data": base64.b64encode(encrypted_inner_payload).decode('utf-8')
        }
        temp_path = self.keyring_path.with_suffix("." + str(os.getpid()))
        with open(os.open(str(temp_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
            _ = yaml.safe_dump(outer_payload, f)
        shutil.move(str(temp_path), self.keyring_path)

        # Update our cached payload
        self.payload = inner_payload


class _KeyringWrapper:
    # Static members
    __shared_instance = None

    # Instance members
    root_path: str = None
    keyring = None
    cached_password: Optional[str] = None
    legacy_keyring = None

    def __init__(self, root_path: str = DEFAULT_ROOT_PATH):
        self.root_path = root_path

        if _KeyringWrapper.keyring:
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

            keyring = _FileKeyring(root_path=self.root_path)
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
        _KeyringWrapper.__shared_instance = self

    @staticmethod
    def get_shared_instance():
        if not _KeyringWrapper.__shared_instance:
            _KeyringWrapper()

        return _KeyringWrapper.__shared_instance

    def get_keyring(self):
        return self.keyring if not self.using_legacy_keyring() else self.legacy_keyring

    def using_legacy_keyring(self) -> bool:
        return self.legacy_keyring is not None

    # Master password support

    def keyring_supports_master_password(self) -> bool:
        return type(self.keyring) in [_FileKeyring]

    def get_cached_master_password(self) -> Optional[str]:
        return self.cached_password

    def set_cached_master_password(self, password: Optional[str]) -> None:
        self.cached_password = password

    def has_master_password(self) -> bool:
        """
        Returns a bool indicating whether the underlying keyring data
        is secured by a master password.
        """
        # TODO: Inspect blob
        return False

    def master_password_is_valid(self, password: Optional[str]) -> bool:
        # TODO: Checkbytes
        return password == "asdfasdf"

    def set_master_password(self, current_password: Optional[str], new_password: str) -> None:
        if self.has_master_password() and not self.master_password_is_valid(current_password):
            raise ValueError("invalid current password")
        # TODO: Encrypt blob
        self.set_cached_master_password(new_password)
        print(f"(TODO: remove) setting password: {new_password}, current_password: {current_password}")

    def remove_master_password(self, current_password: Optional[str]) -> None:
        if _KeyringWrapper.has_master_password() and not _KeyringWrapper.master_password_is_valid(current_password):
            raise ValueError("invalid current password")
        print(f"(TODO: remove) removing password: current_password: {current_password}")

    # Legacy keyring migration
    def migrate_legacy_keyring(self):
        assert self.keyring_supports_master_password()
        print("Migrating contents from legacy keyring")
        keychain = Keychain()
        all_private_keys = keychain.get_all_private_keys()
        index = 0
        for (private_key, key_bytes) in all_private_keys:
            self.keyring.set_password(
                keychain._get_service(),
                keychain._get_private_key_user(index),
                key_bytes)
            index += 1

        # Stop using the legacy keyring
        # TODO: Clear out the legacy keyring's contents?
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
        if self.using_legacy_keyring() and Keychain.has_cached_password():
            print("(TODO: remove) ***** set_password called while using legacy keyring: will migrate")
            self.migrate_legacy_keyring()

        self.get_keyring().set_password(service, user, password_bytes)

    def delete_password(self, service: str, user: str):
        # On the first write while using the legacy keyring, we'll start migration
        if self.using_legacy_keyring() and Keychain.has_cached_password():
            print("(TODO: remove) ***** delete_password called while using legacy keyring: will migrate")
            self.migrate_legacy_keyring()

        self.get_keyring().delete_password(service, user)


def obtain_current_password(prompt: str = "Password: ", use_password_cache: bool = False) -> str:
    print(f"(TODO: remove) obtain_current_password: use_password_cache: {use_password_cache}")

    if use_password_cache:
        password = _KeyringWrapper.get_shared_instance().get_cached_master_password()
        if password:
            if _KeyringWrapper.get_shared_instance().master_password_is_valid(password):
                return password
            else:
                # Cached password is bad, clear the cache
                _KeyringWrapper.get_shared_instance().set_cached_master_password(None)

    for i in range(MAX_RETRIES):
        password = getpass(prompt)

        if _KeyringWrapper.get_shared_instance().master_password_is_valid(password):
            # If using the password cache, and the user inputted a password, update the cache
            if use_password_cache:
                _KeyringWrapper.get_shared_instance().set_cached_master_password(password)
            return password

        sleep(FAILED_ATTEMPT_DELAY)
        print("Incorrect password\n")
    raise ValueError("maximum password attempts reached")


def unlock_keyring_if_necessary(use_password_cache=False) -> None:
    if _KeyringWrapper.get_shared_instance().has_master_password():
        obtain_current_password(use_password_cache=use_password_cache)


def unlocks_keyring(use_password_cache=False):
    print(f"(TODO: remove) unlocks_keyring: use_password_cache: {use_password_cache}")

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

    root_path: str
    testing: bool
    user: str

    def __init__(self, root_path: str = DEFAULT_ROOT_PATH, user: str = "user-chia-1.8", testing: bool = False):
        self.root_path = root_path
        self.testing = testing
        self.user = user

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
        read_str = _KeyringWrapper.get_shared_instance().get_password(self._get_service(), user)
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

    # @unlocks_keyring(use_password_cache=True)
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

        _KeyringWrapper.get_shared_instance().set_password(
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

    # @unlocks_keyring
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
                    _KeyringWrapper.get_shared_instance().delete_password(
                        self._get_service(),
                        self._get_private_key_user(index))
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))

    # @unlocks_keyring
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
                _KeyringWrapper.get_shared_instance().delete_password(
                    self._get_service(),
                    self._get_private_key_user(index))
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
                _KeyringWrapper.get_shared_instance().delete_password(
                    self._get_service(),
                    self._get_private_key_user(index))
            except Exception:
                # Some platforms might throw on no existing key
                delete_exception = True

            # Stop when there are no more keys to delete
            if (pkent is None or delete_exception) and index > MAX_KEYS:
                break
            index += 1

    @staticmethod
    def has_master_password() -> bool:
        """
        Returns a bool indicating whether the underlying keyring data
        is secured by a password.
        """
        return _KeyringWrapper.get_shared_instance().has_master_password()

    @staticmethod
    def master_password_is_valid(password: str) -> bool:
        return _KeyringWrapper.get_shared_instance().master_password_is_valid(password)

    @staticmethod
    def has_cached_password() -> bool:
        password = _KeyringWrapper.get_shared_instance().get_cached_master_password()
        return password is not None and len(password) > 0

    @staticmethod
    def set_cached_master_password(password: Optional[str]) -> None:
        _KeyringWrapper.get_shared_instance().set_cached_master_password(password)

    @staticmethod
    def set_master_password(current_password: Optional[str], new_password: str) -> None:
        _KeyringWrapper.get_shared_instance().set_password(current_password, new_password)

    @staticmethod
    def remove_master_password(current_password: Optional[str]) -> None:
        _KeyringWrapper.get_shared_instance().remove_master_password(current_password)
