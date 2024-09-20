from __future__ import annotations

import base64
import contextlib
import os
import shutil
import sys
import threading
from dataclasses import asdict, dataclass, field
from hashlib import pbkdf2_hmac
from pathlib import Path
from secrets import token_bytes
from typing import Any, Dict, Iterator, Optional, Union, cast

import yaml
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305  # pyright: reportMissingModuleSource=false
from typing_extensions import final
from watchdog.events import DirModifiedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from chia.util.default_root import DEFAULT_KEYS_ROOT_PATH
from chia.util.errors import KeychainFingerprintNotFound, KeychainLabelExists, KeychainLabelInvalid
from chia.util.lock import Lockfile
from chia.util.streamable import convert_byte_type

SALT_BYTES = 16  # PBKDF2 param
NONCE_BYTES = 12  # ChaCha20Poly1305 nonce is 12-bytes
HASH_ITERS = 100000  # PBKDF2 param
CHECKBYTES_VALUE = b"5f365b8292ee505b"  # Randomly generated
MAX_LABEL_LENGTH = 65
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


def symmetric_key_from_passphrase(passphrase: str, salt: bytes) -> bytes:
    return pbkdf2_hmac("sha256", passphrase.encode(), salt, HASH_ITERS)


def get_symmetric_key(salt: bytes) -> bytes:
    from chia.cmds.passphrase_funcs import obtain_current_passphrase

    try:
        passphrase = obtain_current_passphrase(use_passphrase_cache=True)
    except Exception as e:
        print(f"Unable to unlock the keyring: {e}")
        sys.exit(1)

    return symmetric_key_from_passphrase(passphrase, salt)


def encrypt_data(input_data: bytes, key: bytes, nonce: bytes) -> bytes:
    encryptor = ChaCha20Poly1305(key)
    data = encryptor.encrypt(nonce, CHECKBYTES_VALUE + input_data, None)
    return data


def decrypt_data(input_data: bytes, key: bytes, nonce: bytes) -> bytes:
    decryptor = ChaCha20Poly1305(key)
    output = decryptor.decrypt(nonce, input_data, None)
    if CHECKBYTES_VALUE != output[: len(CHECKBYTES_VALUE)]:
        raise ValueError("decryption failure (checkbytes)")
    return output[len(CHECKBYTES_VALUE) :]


def default_file_keyring_data() -> DecryptedKeyringData:
    return DecryptedKeyringData({}, {})


def keyring_path_from_root(keys_root_path: Path) -> Path:
    """
    Returns the path to keyring.yaml
    """
    path_filename = keys_root_path / "keyring.yaml"
    return path_filename


class FileKeyringVersionError(Exception):
    def __init__(self, actual_version: int) -> None:
        super().__init__(
            f"Keyring format is unrecognized. Found version {actual_version}"
            f", expected a value <= {MAX_SUPPORTED_VERSION}. "
            "Please update to a newer version"
        )


@final
@dataclass
class FileKeyringContent:
    """
    FileKeyringContent represents the data structure of the keyring file. It contains an encrypted data part which is
    encrypted with a key derived from the user-provided master passphrase.
    """

    # The version of the whole keyring file structure
    version: int = 1
    # Random salt used as a PBKDF2 parameter. Updated when the master passphrase changes
    salt: bytes = field(default_factory=generate_salt)
    # Random nonce used as a ChaCha20Poly1305 parameter. Updated on each write to the file.
    nonce: bytes = field(default_factory=generate_nonce)
    # Encrypted and base64 encoded keyring data.
    # - The data with CHECKBYTES_VALUE prepended is encrypted using ChaCha20Poly1305.
    # - The symmetric key is derived from the master passphrase using PBKDF2.
    data: Optional[str] = None
    # An optional passphrase hint
    passphrase_hint: Optional[str] = None

    def __post_init__(self) -> None:
        self.salt = convert_byte_type(bytes, self.salt)
        self.nonce = convert_byte_type(bytes, self.nonce)

    @classmethod
    def create_from_path(cls, path: Path) -> FileKeyringContent:
        loaded_dict = dict(yaml.safe_load(path.read_text()))
        version = int(loaded_dict["version"])

        if version > MAX_SUPPORTED_VERSION:
            raise FileKeyringVersionError(version)

        return cls(**loaded_dict)

    def write_to_path(self, path: Path) -> None:
        os.makedirs(os.path.dirname(path), 0o700, True)
        temp_path: Path = path.with_suffix("." + str(os.getpid()))
        with open(os.open(str(temp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as f:
            _ = yaml.safe_dump(self.to_dict(), f)
        try:
            os.replace(str(temp_path), path)
        except PermissionError:
            shutil.move(str(temp_path), str(path))

    def get_decrypted_data_dict(self, passphrase: str) -> Dict[str, Any]:
        if self.empty():
            return {}
        key = symmetric_key_from_passphrase(passphrase, self.salt)
        encrypted_data_yml = base64.b64decode(yaml.safe_load(self.data or ""))
        data_yml = decrypt_data(encrypted_data_yml, key, self.nonce)
        return dict(yaml.safe_load(data_yml))

    def update_encrypted_data_dict(
        self, passphrase: str, decrypted_dict: DecryptedKeyringData, update_salt: bool
    ) -> None:
        self.nonce = generate_nonce()
        if update_salt:
            self.salt = generate_salt()
        data_yaml = yaml.safe_dump(decrypted_dict.to_dict())
        key = symmetric_key_from_passphrase(passphrase, self.salt)
        self.data = base64.b64encode(encrypt_data(data_yaml.encode(), key, self.nonce)).decode("utf-8")

    def empty(self) -> bool:
        return self.data is None or len(self.data) == 0

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["salt"] = result["salt"].hex()
        result["nonce"] = result["nonce"].hex()
        return result


@dataclass(frozen=True)
class Key:
    secret: bytes
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def parse(cls, data: str, metadata: Optional[Dict[str, Any]]) -> Key:
        return cls(
            bytes.fromhex(data),
            metadata,
        )

    def to_data(self) -> Union[str, Dict[str, Any]]:
        return self.secret.hex()


Users = Dict[str, Key]
Services = Dict[str, Users]


@dataclass
class DecryptedKeyringData:
    services: Services
    labels: Dict[int, str]  # {fingerprint: label}

    @classmethod
    def from_dict(cls, data_dict: Dict[str, Any]) -> DecryptedKeyringData:
        return cls(
            {
                service: {
                    user: Key.parse(key, data_dict.get("metadata", {}).get(service, {}).get(user))
                    for user, key in users.items()
                }
                for service, users in data_dict.get("keys", {}).items()
            },
            data_dict.get("labels", {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "keys": {
                service: {user: key.to_data() for user, key in users.items()}
                for service, users in self.services.items()
            },
            "labels": self.labels,
            "metadata": {
                service: {user: key.metadata for user, key in users.items() if key.metadata is not None}
                for service, users in self.services.items()
            },
        }


@final
@dataclass
class FileKeyring(FileSystemEventHandler):
    """
    FileKeyring provides a file-based keyring store to manage a FileKeyringContent .The public interface is intended
    to align with the API provided by the keyring module such that the KeyringWrapper class can pick an appropriate
    keyring store backend based on the OS.
    """

    keyring_path: Path
    # Cache of the whole plaintext YAML file contents (never encrypted)
    cached_file_content: FileKeyringContent
    keyring_observer: BaseObserver = field(default_factory=Observer)
    load_keyring_lock: threading.RLock = field(default_factory=threading.RLock)  # Guards access to needs_load_keyring
    needs_load_keyring: bool = False
    # Cache of the decrypted YAML contained in keyring.data
    cached_data_dict: DecryptedKeyringData = field(default_factory=default_file_keyring_data)
    keyring_last_mod_time: Optional[float] = None
    # Key/value pairs to set on the outer payload on the next write
    file_content_properties_for_next_write: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, keys_root_path: Path = DEFAULT_KEYS_ROOT_PATH) -> FileKeyring:
        """
        Creates a fresh keyring.yaml file if necessary. Otherwise, loads and caches file content.
        """
        keyring_path = keyring_path_from_root(keys_root_path)

        try:
            file_content = FileKeyringContent.create_from_path(keyring_path)
        except FileNotFoundError:
            # Write the default file content to disk
            file_content = FileKeyringContent()
            file_content.write_to_path(keyring_path)

        obj = cls(
            keyring_path=keyring_path,
            cached_file_content=file_content,
        )
        obj.setup_keyring_file_watcher()

        return obj

    def __hash__(self) -> int:
        return hash(self.keyring_path)

    @contextlib.contextmanager
    def lock_and_reload_if_required(self) -> Iterator[None]:
        with Lockfile.create(self.keyring_path, timeout=30, poll_interval=0.2):
            self.check_if_keyring_file_modified()
            with self.load_keyring_lock:
                if self.needs_load_keyring:
                    self.load_keyring()
            yield

    def setup_keyring_file_watcher(self) -> None:
        # recursive=True necessary for macOS support
        if not self.keyring_observer.is_alive():
            self.keyring_observer.schedule(  # type: ignore[no-untyped-call]
                self,
                self.keyring_path.parent,
                recursive=True,
            )
            self.keyring_observer.start()  # type: ignore[no-untyped-call]

    def cleanup_keyring_file_watcher(self) -> None:
        if self.keyring_observer.is_alive():
            self.keyring_observer.stop()  # type: ignore[no-untyped-call]
            self.keyring_observer.join()

    def on_modified(self, event: Union[FileSystemEvent, DirModifiedEvent]) -> None:
        self.check_if_keyring_file_modified()

    def check_if_keyring_file_modified(self) -> None:
        try:
            last_modified = os.stat(self.keyring_path).st_mtime
            if not self.keyring_last_mod_time or self.keyring_last_mod_time < last_modified:
                self.keyring_last_mod_time = last_modified
                with self.load_keyring_lock:
                    self.needs_load_keyring = True
        except FileNotFoundError:
            # If the file doesn't exist there's nothing to do...
            pass

    def has_content(self) -> bool:
        """
        Quick test to determine if keyring contains anything in keyring.data.
        """
        return not self.cached_file_content.empty()

    def cached_keys(self) -> Services:
        """
        Returns keyring.data.keys
        """
        return self.cached_data_dict.services

    def cached_labels(self) -> Dict[int, str]:
        """
        Returns keyring.data.labels
        """
        return self.cached_data_dict.labels

    def get_key(self, service: str, user: str) -> Optional[Key]:
        """
        Returns the passphrase named by the 'user' parameter from the cached
        keyring data (does not force a read from disk)
        """
        with self.lock_and_reload_if_required():
            return self.cached_keys().get(service, {}).get(user)

    def set_key(self, service: str, user: str, key: Key) -> None:
        """
        Store the passphrase to the keyring data using the name specified by the
        'user' parameter. Will force a write to keyring.yaml on success.
        """
        with self.lock_and_reload_if_required():
            keys = self.cached_keys()
            # Ensure a dictionary exists for the 'service'
            if keys.get(service) is None:
                keys[service] = {}
            keys[service][user] = key
            self.write_keyring()

    def delete_key(self, service: str, user: str) -> None:
        """
        Deletes the passphrase named by the 'user' parameter from the keyring data
        (will force a write to keyring.yaml on success)
        """
        with self.lock_and_reload_if_required():
            keys = self.cached_keys()
            service_dict = keys.get(service, {})
            if service_dict.pop(user, None):
                if len(service_dict) == 0:
                    keys.pop(service)
                self.write_keyring()

    def get_label(self, fingerprint: int) -> Optional[str]:
        """
        Returns the label for the given fingerprint or None if there is no label assigned.
        """
        with self.lock_and_reload_if_required():
            return self.cached_labels().get(fingerprint)

    def set_label(self, fingerprint: int, label: str) -> None:
        """
        Set a label for the given fingerprint. This will force a write to keyring.yaml on success.
        """
        # First validate the label
        stripped_label = label.strip()
        if len(stripped_label) == 0:
            raise KeychainLabelInvalid(label, "label can't be empty or whitespace only")
        if len(stripped_label) != len(label):
            raise KeychainLabelInvalid(label, "label can't contain leading or trailing whitespaces")
        if len(label) != len(label.replace("\n", "").replace("\t", "")):
            raise KeychainLabelInvalid(label, "label can't contain newline or tab")
        if len(label) > MAX_LABEL_LENGTH:
            raise KeychainLabelInvalid(label, f"label exceeds max length: {len(label)}/{MAX_LABEL_LENGTH}")
        # Then try to set it
        with self.lock_and_reload_if_required():
            labels = self.cached_labels()
            for existing_fingerprint, existing_label in labels.items():
                if label == existing_label:
                    raise KeychainLabelExists(label, existing_fingerprint)
            labels[fingerprint] = label
            self.write_keyring()

    def delete_label(self, fingerprint: int) -> None:
        """
        Removes the label for the fingerprint. This will force a write to keyring.yaml on success.
        """
        with self.lock_and_reload_if_required():
            try:
                self.cached_labels().pop(fingerprint)
            except KeyError as e:
                raise KeychainFingerprintNotFound(fingerprint) from e
            self.write_keyring()

    def check_passphrase(self, passphrase: str, force_reload: bool = False) -> bool:
        """
        Attempts to validate the passphrase by decrypting keyring.data
        contents and checking the checkbytes value
        """
        if force_reload:
            self.cached_file_content = FileKeyringContent.create_from_path(self.keyring_path)

        try:
            self.cached_file_content.get_decrypted_data_dict(passphrase)
            return True
        except Exception:
            return False

    def load_keyring(self, passphrase: Optional[str] = None) -> None:
        from chia.cmds.passphrase_funcs import obtain_current_passphrase

        with self.load_keyring_lock:
            self.needs_load_keyring = False

        self.cached_file_content = FileKeyringContent.create_from_path(self.keyring_path)

        if not self.has_content():
            return

        if passphrase is None:
            # TODO, this prompts for the passphrase interactively, move this out
            passphrase = obtain_current_passphrase(use_passphrase_cache=True)

        self.cached_data_dict = DecryptedKeyringData.from_dict(
            self.cached_file_content.get_decrypted_data_dict(passphrase)
        )

    def write_keyring(self, fresh_salt: bool = False) -> None:
        from chia.cmds.passphrase_funcs import obtain_current_passphrase
        from chia.util.keyring_wrapper import KeyringWrapper

        # Merge in other properties like "passphrase_hint"
        if "passphrase_hint" in self.file_content_properties_for_next_write:
            self.cached_file_content.passphrase_hint = self.file_content_properties_for_next_write["passphrase_hint"]

        # When writing for the first time, we should have a cached passphrase which hasn't been
        # validated (because it can't be validated yet...)
        if not self.has_content() and KeyringWrapper.get_shared_instance().has_cached_master_passphrase():
            # TODO: The above checks, at the time of writing, make sure we get a str here.  A reconsideration of this
            #       interface would be good.
            passphrase = cast(str, KeyringWrapper.get_shared_instance().get_cached_master_passphrase()[0])
        else:
            # TODO, this prompts for the passphrase interactively, move this out
            passphrase = obtain_current_passphrase(use_passphrase_cache=True)

        try:
            self.cached_file_content.update_encrypted_data_dict(passphrase, self.cached_data_dict, fresh_salt)
            self.cached_file_content.write_to_path(self.keyring_path)
            # Cleanup the cached properties now that we wrote the new content to file
            self.file_content_properties_for_next_write = {}
        except Exception:
            # Restore the correct content if we failed to write the updated cache, let it re-raise if loading also fails
            self.cached_file_content = FileKeyringContent.create_from_path(self.keyring_path)

    def get_passphrase_hint(self) -> Optional[str]:
        """
        Return the passphrase hint (if set). The hint data may not yet be written to the keyring, so we
        return the hint data either from the staging dict (file_content_properties_for_next_write), or
        from cached_file_content (loaded from the keyring)
        """
        passphrase_hint: Optional[str] = self.file_content_properties_for_next_write.get("passphrase_hint", None)
        if passphrase_hint is None:
            passphrase_hint = self.cached_file_content.passphrase_hint
        return passphrase_hint

    def set_passphrase_hint(self, passphrase_hint: Optional[str]) -> None:
        """
        Store the new passphrase hint in the staging dict (file_content_properties_for_next_write) to
        be written-out on the next write to the keyring.
        """
        self.file_content_properties_for_next_write["passphrase_hint"] = passphrase_hint
