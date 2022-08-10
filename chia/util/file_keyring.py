from __future__ import annotations

import base64
import contextlib
import os
import shutil
import sys
import threading
from dataclasses import dataclass, field
from functools import wraps
from hashlib import pbkdf2_hmac
from pathlib import Path
from secrets import token_bytes
from typing import Any, Callable, Dict, Iterator, Optional, Union

import yaml
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305  # pyright: reportMissingModuleSource=false
from typing_extensions import final
from watchdog.events import DirModifiedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from chia.util.default_root import DEFAULT_KEYS_ROOT_PATH
from chia.util.lock import Lockfile

SALT_BYTES = 16  # PBKDF2 param
NONCE_BYTES = 12  # ChaCha20Poly1305 nonce is 12-bytes
HASH_ITERS = 100000  # PBKDF2 param
CHECKBYTES_VALUE = b"5f365b8292ee505b"  # Randomly generated
MAX_SUPPORTED_VERSION = 1  # Max supported file format version


def generate_nonce() -> bytes:
    """
    Creates a nonce to be used by ChaCha20Poly1305. This should be called each time
    the payload is encrypted.
    """
    return token_bytes(NONCE_BYTES)


def generate_salt() -> bytes:
    """
    Creates a salt to be used in combination with the master passphrase to derive
    a symmetric key using PBKDF2
    """
    return token_bytes(SALT_BYTES)


def have_valid_checkbytes(decrypted_data: bytes) -> bool:
    return CHECKBYTES_VALUE == decrypted_data[: len(CHECKBYTES_VALUE)]


def symmetric_key_from_passphrase(passphrase: str, salt: bytes) -> bytes:
    return pbkdf2_hmac("sha256", passphrase.encode(), salt, HASH_ITERS)


def get_symmetric_key(salt: bytes) -> bytes:
    from chia.util.keychain import obtain_current_passphrase

    try:
        passphrase = obtain_current_passphrase(use_passphrase_cache=True)
    except Exception as e:
        print(f"Unable to unlock the keyring: {e}")
        sys.exit(1)

    return symmetric_key_from_passphrase(passphrase, salt)


def encrypt_data(input_data: bytes, key: bytes, nonce: bytes) -> bytes:
    encryptor = ChaCha20Poly1305(key)
    data = encryptor.encrypt(nonce, input_data, None)
    return data


def decrypt_data(input_data: bytes, key: bytes, nonce: bytes) -> bytes:
    decryptor = ChaCha20Poly1305(key)
    output = decryptor.decrypt(nonce, input_data, None)
    return output


def default_outer_payload() -> Dict[str, Any]:
    return {"version": 1}


def keyring_path_from_root(keys_root_path: Path) -> Path:
    """
    Returns the path to keyring.yaml
    """
    path_filename = keys_root_path / "keyring.yaml"
    return path_filename


FileKeyringUnlockingCallable = Callable[..., Optional[str]]


def loads_keyring(method: FileKeyringUnlockingCallable) -> FileKeyringUnlockingCallable:
    """
    Decorator which lazily loads the FileKeyring data
    """

    @wraps(method)
    def inner(self: FileKeyring, *args: object, **kwargs: object) -> Optional[str]:
        self.check_if_keyring_file_modified()

        # Check the outer payload for 'data', and check if we have a decrypted cache (payload_cache)
        with self.load_keyring_lock:
            if (self.has_content() and not self.payload_cache) or self.needs_load_keyring:
                self.load_keyring()
        return method(self, *args, **kwargs)

    return inner


@final
@dataclass
class FileKeyring(FileSystemEventHandler):  # type: ignore[misc] # Class cannot subclass "" (has type "Any")
    """
    FileKeyring provides an file-based keyring store that is encrypted to a key derived
    from the user-provided master passphrase. The public interface is intended to align
    with the API provided by the keyring module such that the KeyringWrapper class can
    pick an appropriate keyring store backend based on the OS.

    The keyring file format uses YAML with a few top-level keys:

        # Keyring file version, currently 1
        version: <int>

        # Random salt used as a PBKDF2 parameter. Updated when the master passphrase changes
        salt: <hex string of 16 bytes>

        # Random nonce used as a ChaCha20Poly1305 parameter. Updated on each write to the file
        nonce: <hex string of 12 bytes>

        # The encrypted data. Internally, a checkbytes value is concatenated with the
        # inner payload (a YAML document). The inner payload YAML contains a "keys" element
        # that holds a dictionary of keys.
        data: <base64-encoded string of encrypted inner-payload>

        # An optional passphrase hint
        passphrase_hint: <cleartext string>

    The file is encrypted using ChaCha20Poly1305. The symmetric key is derived from the
    master passphrase using PBKDF2. The nonce is updated each time the file is written-to.
    The salt is updated each time the master passphrase is changed.
    """

    keyring_path: Path
    keyring_observer: Observer = field(default_factory=Observer)
    load_keyring_lock: threading.RLock = field(default_factory=threading.RLock)  # Guards access to needs_load_keyring
    needs_load_keyring: bool = False
    salt: Optional[bytes] = None  # PBKDF2 param
    # Cache of the decrypted YAML contained in outer_payload_cache['data']
    payload_cache: Dict[str, Any] = field(default_factory=dict)
    # Cache of the plaintext YAML "outer" contents (never encrypted)
    outer_payload_cache: Dict[str, Any] = field(default_factory=dict)
    keyring_last_mod_time: Optional[float] = None
    # Key/value pairs to set on the outer payload on the next write
    outer_payload_properties_for_next_write: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, keys_root_path: Path = DEFAULT_KEYS_ROOT_PATH) -> FileKeyring:
        """
        Creates a fresh keyring.yaml file if necessary. Otherwise, loads and caches the
        outer (plaintext) payload
        """
        keyring_path = keyring_path_from_root(keys_root_path)
        obj = cls(keyring_path=keyring_path)

        if not keyring_path.exists():
            # Super simple payload if starting from scratch
            outer_payload = default_outer_payload()
            obj.write_data_to_keyring(outer_payload)
            obj.outer_payload_cache = outer_payload
        else:
            obj.load_outer_payload()

        obj.setup_keyring_file_watcher()

        return obj

    def __hash__(self) -> int:
        return hash(self.keyring_path)

    @contextlib.contextmanager
    def lockfile(self) -> Iterator[None]:
        with Lockfile.create(self.keyring_path, timeout=30, poll_interval=0.2):
            yield

    def setup_keyring_file_watcher(self) -> None:
        # recursive=True necessary for macOS support
        if not self.keyring_observer.is_alive():
            self.keyring_observer.schedule(self, self.keyring_path.parent, recursive=True)
            self.keyring_observer.start()

    def cleanup_keyring_file_watcher(self) -> None:
        if self.keyring_observer.is_alive():
            self.keyring_observer.stop()
            self.keyring_observer.join()

    def on_modified(self, event: Union[FileSystemEvent, DirModifiedEvent]) -> None:
        self.check_if_keyring_file_modified()

    def check_if_keyring_file_modified(self) -> None:
        if self.keyring_path.exists():
            try:
                last_modified = os.stat(self.keyring_path).st_mtime
                if not self.keyring_last_mod_time or self.keyring_last_mod_time < last_modified:
                    self.keyring_last_mod_time = last_modified
                    with self.load_keyring_lock:
                        self.needs_load_keyring = True
            except FileNotFoundError:
                # Shouldn't happen, but if the file doesn't exist there's nothing to do...
                pass

    def has_content(self) -> bool:
        """
        Quick test to determine if keyring is populated. The "data" value is expected
        to be encrypted.
        """
        if self.outer_payload_cache is not None and self.outer_payload_cache.get("data"):
            return True
        return False

    def ensure_cached_keys_dict(self) -> Dict[str, Dict[str, str]]:
        """
        Returns payload_cache["keys"], ensuring that it's created if necessary
        """
        if self.payload_cache.get("keys") is None:
            self.payload_cache["keys"] = {}
        keys_dict: Dict[str, Dict[str, str]] = self.payload_cache["keys"]
        return keys_dict

    @loads_keyring
    def _inner_get_password(self, service: str, user: str) -> Optional[str]:
        return self.ensure_cached_keys_dict().get(service, {}).get(user)

    def get_password(self, service: str, user: str) -> Optional[str]:
        """
        Returns the passphrase named by the 'user' parameter from the cached
        keyring data (does not force a read from disk)
        """
        with self.lockfile():
            return self._inner_get_password(service, user)

    @loads_keyring
    def _inner_set_password(self, service: str, user: str, passphrase: str) -> None:
        keys = self.ensure_cached_keys_dict()
        # Convert the passphrase to a string (if necessary)
        passphrase = bytes(passphrase).hex() if type(passphrase) == bytes else str(passphrase)  # type: ignore

        # Ensure a dictionary exists for the 'service'
        if keys.get(service) is None:
            keys[service] = {}
        service_dict = keys[service]
        service_dict[user] = passphrase
        keys[service] = service_dict
        self.payload_cache["keys"] = keys
        self.write_keyring()  # Updates the cached payload (self.payload_cache) on success

    def set_password(self, service: str, user: str, passphrase: str) -> None:
        """
        Store the passphrase to the keyring data using the name specified by the
        'user' parameter. Will force a write to keyring.yaml on success.
        """
        with self.lockfile():
            self._inner_set_password(service, user, passphrase)

    @loads_keyring
    def _inner_delete_password(self, service: str, user: str) -> None:
        keys = self.ensure_cached_keys_dict()

        service_dict = keys.get(service, {})
        if service_dict.pop(user, None):
            if len(service_dict) == 0:
                keys.pop(service)
            self.payload_cache["keys"] = keys
            self.write_keyring()  # Updates the cached payload (self.payload_cache) on success

    def delete_password(self, service: str, user: str) -> None:
        """
        Deletes the passphrase named by the 'user' parameter from the keyring data
        (will force a write to keyring.yaml on success)
        """
        with self.lockfile():
            self._inner_delete_password(service, user)

    def check_passphrase(self, passphrase: str, force_reload: bool = False) -> bool:
        """
        Attempts to validate the passphrase by decrypting the outer_payload_cache["data"]
        contents and checking the checkbytes value
        """
        if force_reload or len(self.outer_payload_cache) == 0:
            self.load_outer_payload()

        if not self.salt or len(self.outer_payload_cache) == 0:
            return False

        nonce = None
        nonce_str = self.outer_payload_cache.get("nonce")
        if nonce_str:
            nonce = bytes.fromhex(nonce_str)

        if not nonce:
            return False

        key = symmetric_key_from_passphrase(passphrase, self.salt)
        encrypted_data = base64.b64decode(yaml.safe_load(self.outer_payload_cache.get("data") or ""))

        try:
            decrypted_data = decrypt_data(encrypted_data, key, nonce)
        except Exception:
            return False
        return have_valid_checkbytes(decrypted_data)

    def load_outer_payload(self) -> None:
        if not self.keyring_path.is_file():
            raise ValueError("Keyring file not found")

        self.outer_payload_cache = dict(yaml.safe_load(open(self.keyring_path, "r")))
        version = int(self.outer_payload_cache["version"])
        if version > MAX_SUPPORTED_VERSION:
            print(
                f"Keyring format is unrecognized. Found version {version}"
                ", expected a value <= {MAX_SUPPORTED_VERSION}"
            )
            print("Please update to a newer version")
            sys.exit(1)

        # Attempt to load the salt. It may not be present if the keyring is empty.
        salt = self.outer_payload_cache.get("salt")
        if salt:
            self.salt = bytes.fromhex(salt)

    def load_keyring(self, passphrase: Optional[str] = None) -> None:
        with self.load_keyring_lock:
            self.needs_load_keyring = False

        self.load_outer_payload()

        # Missing the salt or nonce indicates that the keyring doesn't have any keys stored.
        salt_str = self.outer_payload_cache.get("salt")
        nonce_str = self.outer_payload_cache.get("nonce")
        if not salt_str or not nonce_str:
            return

        salt = bytes.fromhex(salt_str)
        nonce = bytes.fromhex(nonce_str)
        key = None

        if passphrase:
            key = symmetric_key_from_passphrase(passphrase, salt)
        else:
            key = get_symmetric_key(salt)

        encrypted_payload = base64.b64decode(yaml.safe_load(self.outer_payload_cache.get("data") or ""))
        decrypted_data = decrypt_data(encrypted_payload, key, nonce)
        if not have_valid_checkbytes(decrypted_data):
            raise ValueError("decryption failure (checkbytes)")
        inner_payload = decrypted_data[len(CHECKBYTES_VALUE) :]

        self.payload_cache = dict(yaml.safe_load(inner_payload))

    def is_first_write(self) -> bool:
        return self.outer_payload_cache == default_outer_payload()

    def write_keyring(self, fresh_salt: bool = False) -> None:
        from chia.util.keyring_wrapper import KeyringWrapper

        inner_payload = self.payload_cache
        inner_payload_yaml = yaml.safe_dump(inner_payload)
        nonce = generate_nonce()
        key = None

        # Update the salt when changing the master passphrase or when the keyring is new (empty)
        if fresh_salt or not self.salt:
            self.salt = generate_salt()

        salt = self.salt

        # When writing for the first time, we should have a cached passphrase which hasn't been
        # validated (because it can't be validated yet...)
        # TODO Fix hinting in `KeyringWrapper` to get rid of the ignores below
        if self.is_first_write() and KeyringWrapper.get_shared_instance().has_cached_master_passphrase():  # type: ignore[no-untyped-call]  # noqa: E501
            key = symmetric_key_from_passphrase(
                KeyringWrapper.get_shared_instance().get_cached_master_passphrase()[0], self.salt  # type: ignore[no-untyped-call]  # noqa: E501
            )
        else:
            # Prompt for the passphrase interactively and derive the key
            key = get_symmetric_key(salt)

        encrypted_inner_payload = encrypt_data(CHECKBYTES_VALUE + inner_payload_yaml.encode(), key, nonce)

        outer_payload = {
            "version": 1,
            "salt": self.salt.hex(),
            "nonce": nonce.hex(),
            "data": base64.b64encode(encrypted_inner_payload).decode("utf-8"),
            "passphrase_hint": self.outer_payload_cache.get("passphrase_hint", None),
        }

        # Merge in other properties like "passphrase_hint"
        outer_payload.update(self.outer_payload_properties_for_next_write)
        self.outer_payload_properties_for_next_write = {}

        self.write_data_to_keyring(outer_payload)

        # Update our cached payload
        self.outer_payload_cache = outer_payload
        self.payload_cache = inner_payload

    def write_data_to_keyring(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.keyring_path), 0o700, True)
        temp_path: Path = self.keyring_path.with_suffix("." + str(os.getpid()))
        with open(os.open(str(temp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as f:
            _ = yaml.safe_dump(data, f)
        try:
            os.replace(str(temp_path), self.keyring_path)
        except PermissionError:
            shutil.move(str(temp_path), str(self.keyring_path))

    def get_passphrase_hint(self) -> Optional[str]:
        """
        Return the passphrase hint (if set). The hint data may not yet be written to the keyring, so we
        return the hint data either from the staging dict (outer_payload_properties_for_next_write), or
        from outer_payload_cache (loaded from the keyring)
        """
        passphrase_hint: Optional[str] = self.outer_payload_properties_for_next_write.get("passphrase_hint", None)
        if passphrase_hint is None:
            passphrase_hint = self.outer_payload_cache.get("passphrase_hint", None)
        return passphrase_hint

    def set_passphrase_hint(self, passphrase_hint: Optional[str]) -> None:
        """
        Store the new passphrase hint in the staging dict (outer_payload_properties_for_next_write) to
        be written-out on the next write to the keyring.
        """
        self.outer_payload_properties_for_next_write["passphrase_hint"] = passphrase_hint
