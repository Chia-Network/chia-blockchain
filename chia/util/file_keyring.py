import base64
import os
import shutil
import sys
import yaml

from chia.util.default_root import DEFAULT_ROOT_PATH
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305  # pyright: reportMissingModuleSource=false
from functools import wraps
from hashlib import pbkdf2_hmac
from pathlib import Path
from secrets import token_bytes
from typing import Optional


SALT_BYTES = 16  # PBKDF2 param
NONCE_BYTES = 12  # ChaCha20Poly1305 nonce is 12-bytes
HASH_ITERS = 100000  # PBKDF2 param
CHECKBYTES_VALUE = b"5f365b8292ee505b"  # Randomly generated
MAX_SUPPORTED_VERSION = 1  # Max supported file format version


def loads_keyring(method):
    """
    Decorator which lazily loads the FileKeyring data
    """

    @wraps(method)
    def inner(self, *args, **kwargs):
        # Check the outer payload for 'data', and check if we have a decrypted cache (payload_cache)
        if self.has_content() and not self.payload_cache:
            self.load_keyring()
        return method(self, *args, **kwargs)

    return inner


class FileKeyring:
    """
    FileKeyring provides an file-based keyring store that is encrypted to a key derived
    from the user-provided master password. The public interface is intended to align
    with the API provided by the keyring module such that the KeyringWrapper class can
    pick an appropriate keyring store backend based on the OS.

    The keyring file format uses YAML with a few top-level keys:

        # Keyring file version, currently 1
        version: <int>

        # Random salt used as a PBKDF2 parameter. Updated when the master password changes
        salt: <hex string of 16 bytes>

        # Random nonce used as a ChaCha20Poly1305 parameter. Updated on each write to the file
        nonce: <hex string of 12 bytes>

        # The encrypted data. Internally, a checkbytes value is concatenated with the
        # inner payload (a YAML document). The inner payload YAML contains a "keys" element
        # that holds a dictionary of keys.
        data: <base64-encoded string of encrypted inner-payload>

    The file is encrypted using ChaCha20Poly1305. The symmetric key is derived from the
    master password using PBKDF2. The nonce is updated each time the file is written-to.
    The salt is updated each time the master password is changed.
    """

    keyring_path: Optional[Path] = None
    salt: Optional[bytes] = None  # PBKDF2 param
    payload_cache: dict = {}  # Cache of the decrypted YAML contained in outer_payload_cache['data']
    outer_payload_cache: dict = {}  # Cache of the plaintext YAML "outer" contents (never encrypted)

    @staticmethod
    def keyring_path_from_root(root_path: Path) -> Path:
        """
        Returns the path to keyring.yaml
        """
        path_filename = root_path / "config" / "keyring.yaml"
        return path_filename

    def __init__(self, root_path: Path = DEFAULT_ROOT_PATH):
        """
        Creates a fresh keyring.yaml file if necessary. Otherwise, loads and caches the
        outer (plaintext) payload
        """
        self.keyring_path = FileKeyring.keyring_path_from_root(root_path)
        self.payload_cache = {}  # This is used as a building block for adding keys etc if the keyring is empty

        if not self.keyring_path.exists():
            # Super simple payload if starting from scratch
            outer_payload = FileKeyring.default_outer_payload()
            self.write_data_to_keyring(outer_payload)
            self.outer_payload_cache = outer_payload
        else:
            self.load_outer_payload()

    @staticmethod
    def default_outer_payload() -> dict:
        return {"version": 1}

    @staticmethod
    def generate_nonce() -> bytes:
        """
        Creates a nonce to be used by ChaCha20Poly1305. This should be called each time
        the payload is encrypted.
        """
        return token_bytes(NONCE_BYTES)

    @staticmethod
    def generate_salt() -> bytes:
        """
        Creates a salt to be used in combination with the master password to derive
        a symmetric key using PBKDF2
        """
        return token_bytes(SALT_BYTES)

    def has_content(self) -> bool:
        """
        Quick test to determine if keyring is populated. The "data" value is expected
        to be encrypted.
        """
        if self.outer_payload_cache is not None and self.outer_payload_cache.get("data"):
            return True
        return False

    def ensure_cached_keys_dict(self) -> dict:
        """
        Returns payload_cache["keys"], ensuring that it's created if necessary
        """
        if self.payload_cache.get("keys") is None:
            self.payload_cache["keys"] = {}
        return self.payload_cache["keys"]

    @loads_keyring
    def get_password(self, service: str, user: str) -> Optional[str]:
        """
        Returns the password named by the 'user' parameter from the cached
        keyring data (does not force a read from disk)
        """
        return self.ensure_cached_keys_dict().get(service, {}).get(user)

    @loads_keyring
    def set_password(self, service: str, user: str, password_bytes: bytes):
        """
        Store the password to the keyring data using the name specified by the
        'user' parameter. Will force a write to keyring.yaml on success.
        """
        keys = self.ensure_cached_keys_dict()
        # Convert the password to a string (if necessary)
        password = password_bytes.hex() if type(password_bytes) == bytes else str(password_bytes)

        # Ensure a dictionary exists for the 'service'
        if keys.get(service) is None:
            keys[service] = {}
        service_dict = keys[service]
        service_dict[user] = password
        keys[service] = service_dict
        self.payload_cache["keys"] = keys
        self.write_keyring()  # Updates the cached payload (self.payload_cache) on success

    @loads_keyring
    def delete_password(self, service: str, user: str):
        """
        Deletes the password named by the 'user' parameter from the keyring data
        (will force a write to keyring.yaml on success)
        """
        keys = self.ensure_cached_keys_dict()

        service_dict = keys.get(service, {})
        if service_dict.pop(user, None):
            if len(service_dict) == 0:
                keys.pop(service)
            self.payload_cache["keys"] = keys
            self.write_keyring()  # Updates the cached payload (self.payload_cache) on success

    def check_password(self, password: str) -> bool:
        """
        Attempts to validate the password by decrypting the outer_payload_cache["data"]
        contents and checking the checkbytes value
        """
        if len(self.outer_payload_cache) == 0:
            self.load_outer_payload()

        if not self.salt or len(self.outer_payload_cache) == 0:
            return False

        nonce = None
        nonce_str = self.outer_payload_cache.get("nonce")
        if nonce_str:
            nonce = bytes.fromhex(nonce_str)

        if not nonce:
            return False

        key = FileKeyring.symmetric_key_from_password(password, self.salt)
        encrypted_data = base64.b64decode(yaml.safe_load(self.outer_payload_cache.get("data") or ""))

        try:
            decrypted_data = self.decrypt_data(encrypted_data, key, nonce)
        except Exception:
            return False
        return self.have_valid_checkbytes(decrypted_data)

    def have_valid_checkbytes(self, decrypted_data: bytes) -> bool:
        checkbytes = decrypted_data[: len(CHECKBYTES_VALUE)]
        return checkbytes == CHECKBYTES_VALUE

    @staticmethod
    def symmetric_key_from_password(password: str, salt: bytes) -> bytes:
        return pbkdf2_hmac("sha256", password.encode(), salt, HASH_ITERS)

    @staticmethod
    def get_symmetric_key(salt: bytes) -> bytes:
        from chia.util.keychain import obtain_current_password

        try:
            password = obtain_current_password(use_password_cache=True)
        except Exception as e:
            print(f"Unable to unlock the keyring: {e}")
            sys.exit(1)

        return FileKeyring.symmetric_key_from_password(password, salt)

    def encrypt_data(self, input_data: bytes, key: bytes, nonce: bytes) -> bytes:
        encryptor = ChaCha20Poly1305(key)
        data = encryptor.encrypt(nonce, input_data, None)
        return data

    def decrypt_data(self, input_data: bytes, key: bytes, nonce: bytes) -> bytes:
        decryptor = ChaCha20Poly1305(key)
        output = decryptor.decrypt(nonce, input_data, None)
        return output

    def load_outer_payload(self):
        if not self.keyring_path.is_file():
            raise ValueError("Keyring file not found")

        self.outer_payload_cache = dict(yaml.safe_load(open(self.keyring_path, "r")))
        version = int(self.outer_payload_cache.get("version"))
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

    def load_keyring(self, password: str = None):
        self.load_outer_payload()

        # Missing the salt or nonce indicates that the keyring doesn't have any keys stored.
        salt_str = self.outer_payload_cache.get("salt")
        nonce_str = self.outer_payload_cache.get("nonce")
        if not salt_str or not nonce_str:
            return

        salt = bytes.fromhex(salt_str)
        nonce = bytes.fromhex(nonce_str)
        key = None

        if password:
            key = FileKeyring.symmetric_key_from_password(password, salt)
        else:
            key = FileKeyring.get_symmetric_key(salt)

        encrypted_payload = base64.b64decode(yaml.safe_load(self.outer_payload_cache.get("data") or ""))
        decrypted_data = self.decrypt_data(encrypted_payload, key, nonce)
        if not self.have_valid_checkbytes(decrypted_data):
            raise ValueError("decryption failure (checkbytes)")
        inner_payload = decrypted_data[len(CHECKBYTES_VALUE) :]

        self.payload_cache = dict(yaml.safe_load(inner_payload))

    def write_keyring(self, fresh_salt: bool = False):
        from chia.util.keyring_wrapper import DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD

        inner_payload = self.payload_cache
        inner_payload_yaml = yaml.safe_dump(inner_payload)
        nonce = FileKeyring.generate_nonce()
        key = None

        # Update the salt when changing the master password
        if fresh_salt:
            self.salt = FileKeyring.generate_salt()

        using_default_password = False
        # If the salt is missing, we're working with an empty keyring
        if not self.salt:
            self.salt = FileKeyring.generate_salt()
            using_default_password = True

        salt = self.salt

        if using_default_password:
            key = FileKeyring.symmetric_key_from_password(DEFAULT_PASSWORD_IF_NO_MASTER_PASSWORD, self.salt)
        else:
            key = FileKeyring.get_symmetric_key(salt)

        encrypted_inner_payload = self.encrypt_data(CHECKBYTES_VALUE + inner_payload_yaml.encode(), key, nonce)

        outer_payload = {
            "version": 1,
            "salt": self.salt.hex(),
            "nonce": nonce.hex(),
            "data": base64.b64encode(encrypted_inner_payload).decode("utf-8"),
        }

        self.write_data_to_keyring(outer_payload)

        # Update our cached payload
        self.outer_payload_cache = outer_payload
        self.payload_cache = inner_payload

    def write_data_to_keyring(self, data):
        os.makedirs(os.path.dirname(self.keyring_path), 0o775, True)
        temp_path = self.keyring_path.with_suffix("." + str(os.getpid()))
        with open(os.open(str(temp_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
            _ = yaml.safe_dump(data, f)
        shutil.move(str(temp_path), self.keyring_path)

    def prepare_for_migration(self):
        if not self.payload_cache:
            self.payload_cache = {"keys": {}}

        if not self.salt:
            self.salt = FileKeyring.generate_salt()
