from secrets import token_bytes
from typing import List, Tuple, Optional

import keyring as keyring_main
import pkg_resources
from bitstring import BitArray
from blspy import ExtendedPrivateKey, ExtendedPublicKey, PrivateKey

from src.util.byte_types import hexstr_to_bytes
from src.util.hash import std_hash
from sys import platform
from keyrings.cryptfile.cryptfile import CryptFileKeyring

if platform == "win32" or platform == "cygwin":
    import keyring.backends.Windows

    keyring.set_keyring(keyring.backends.Windows.WinVaultKeyring())
elif platform == "darwin":
    import keyring.backends.OS_X

    keyring.set_keyring(keyring.backends.OS_X.Keyring())
elif platform == "linux":
    keyring = CryptFileKeyring()
    keyring.keyring_key = "your keyring password"
else:
    keyring = keyring_main


def bip39_word_list() -> str:
    return pkg_resources.resource_string(__name__, "english.txt").decode()


def generate_mnemonic() -> List[str]:
    seed_bytes = token_bytes(32)
    mnemonic = bytes_to_mnemonic(seed_bytes)
    return mnemonic


def bytes_to_mnemonic(seed_bytes: bytes):
    seed_array = bytearray(seed_bytes)
    word_list = bip39_word_list().splitlines()

    checksum = bytes(std_hash(seed_bytes))

    seed_array.append(checksum[0])
    bytes_for_mnemonic = bytes(seed_array)
    bitarray = BitArray(bytes_for_mnemonic)
    mnemonics = []

    for i in range(0, 24):
        start = i * 11
        end = start + 11
        bits = bitarray[start:end]
        m_word_poition = bits.uint
        m_word = word_list[m_word_poition]
        mnemonics.append(m_word)

    return mnemonics


def seed_from_mnemonic(mnemonic: List[str]):
    word_list = {word: i for i, word in enumerate(bip39_word_list().splitlines())}
    bit_array = BitArray()
    for i in range(0, 24):
        word = mnemonic[i]
        value = word_list[word]
        bit_array.append(BitArray(uint=value, length=11))

    all_bytes = bit_array.bytes
    entropy_bytes = all_bytes[:32]
    checksum_bytes = all_bytes[32]
    checksum = std_hash(entropy_bytes)

    if checksum[0] != checksum_bytes:
        raise ValueError("Invalid order of mnemonic words")

    return entropy_bytes


class Keychain:
    """
    The keychain stores two types of keys: private keys, which are ExtendedPrivateKeys from blspy,
    and private key seeds, which are bytes objects that are used as a seed to construct
    ExtendedPrivateKeys. Private key seeds are converted to mnemonics when shown to users.

    Both types of keys are stored as hex strings in the python keyring, and the implementation of
    the keyring depends on OS. Both types of keys can be added, and get_private_keys returns a
    list of all keys.
    """

    testing: bool
    user: str

    def __init__(self, user: str = "user", testing: bool = False):
        self.testing = testing
        self.user = user

    def _get_service(self):
        if self.testing:
            return f"chia-{self.user}-test"
        else:
            return f"chia-{self.user}"

    def _get_stored_entropy(self, user: str):
        return keyring.get_password(self._get_service(), user)

    def _get_private_key_seed_user(self, index: int):
        if self.testing:
            return f"wallet-{self.user}-test-{index}"
        else:
            return f"wallet-{self.user}-{index}"

    def _get_private_key_user(self, index: int):
        if self.testing:
            return f"wallet-{self.user}-raw-test-{index}"
        else:
            return f"wallet-{self.user}-raw-{index}"

    def _get_free_private_key_seed_index(self) -> int:
        index = 0
        while True:
            key = self._get_stored_entropy(self._get_private_key_seed_user(index))
            if key is None:
                return index
            index += 1

    def _get_free_private_key_index(self):
        index = 0
        while True:
            key = self._get_stored_entropy(self._get_private_key_user(index))
            if key is None:
                return index
            index += 1

    def add_private_key_seed(self, seed: bytes):
        """
        Adds a private key seed to the keychain. This is the best way to add keys, since they can
        be backed up to mnemonics. A seed is used to generate a BLS ExtendedPrivateKey.
        """
        index = self._get_free_private_key_seed_index()
        key = ExtendedPrivateKey.from_seed(seed)
        if key.get_public_key().get_fingerprint() in [
            epk.get_public_key().get_fingerprint() for epk in self.get_all_public_keys()
        ]:
            # Prevents duplicate add
            return
        keyring.set_password(
            self._get_service(), self._get_private_key_seed_user(index), seed.hex()
        )

    def add_private_key(self, key: ExtendedPrivateKey):
        """
        Adds an extended private key to the keychain. This is used for old keys from keys.yaml.
        The new method is adding a seed (which can be converted into a mnemonic) instead.
        """

        key_bytes = bytes(key)
        index = self._get_free_private_key_index()
        if key.get_public_key().get_fingerprint() in [
            epk.get_public_key().get_fingerprint() for epk in self.get_all_public_keys()
        ]:
            # Prevents duplicate add
            return
        keyring.set_password(
            self._get_service(), self._get_private_key_user(index), key_bytes.hex()
        )

    def add_private_key_not_extended(self, key_not_extended: PrivateKey):
        """
        Creates a new key, and takes only the prefix information (chain code, version, etc).
        This is used to migrate pool_sks from keys.yaml, which are not extended. Then adds
        the key to the keychain.
        """

        key_bytes = bytes(key_not_extended)
        new_extended_bytes = bytearray(
            bytes(ExtendedPrivateKey.from_seed(token_bytes(32)))
        )
        final_extended_bytes = bytes(new_extended_bytes[: -len(key_bytes)] + key_bytes)
        key = ExtendedPrivateKey.from_bytes(final_extended_bytes)
        assert len(final_extended_bytes) == len(new_extended_bytes)
        assert key.get_private_key() == key_not_extended
        self.add_private_key(key)

    def get_all_private_keys(self) -> List[Tuple[ExtendedPrivateKey, Optional[bytes]]]:
        """
        Returns all private keys (both seed-derived keys and raw ExtendedPrivateKeys), and
        the second value in the tuple is the bytes seed if it exists, otherwise None.
        """
        all_keys: List[Tuple[ExtendedPrivateKey, Optional[bytes]]] = []

        # Keys that have a seed are added first
        index = 0
        seed_hex = self._get_stored_entropy(self._get_private_key_seed_user(index))
        while seed_hex is not None and len(seed_hex) > 0:
            key = ExtendedPrivateKey.from_seed(hexstr_to_bytes(seed_hex))
            all_keys.append((key, hexstr_to_bytes(seed_hex)))
            index += 1
            seed_hex = self._get_stored_entropy(self._get_private_key_seed_user(index))

        # Keys without a seed are added after
        index = 0
        key_hex = self._get_stored_entropy(self._get_private_key_user(index))
        while key_hex is not None and len(key_hex) > 0:
            key = ExtendedPrivateKey.from_bytes(hexstr_to_bytes(key_hex))
            all_keys.append((key, None))
            index += 1
            key_hex = self._get_stored_entropy(self._get_private_key_user(index))
        return all_keys

    def get_all_public_keys(self) -> List[ExtendedPublicKey]:
        """
        Returns all public keys (both seed-derived keys and raw keys).
        """
        return [sk.get_extended_public_key() for (sk, _) in self.get_all_private_keys()]

    def delete_key_by_fingerprint(self, fingerprint: int):
        """
        Deletes all keys which have the given public key fingerprint.
        """

        index = 0
        key_hex = self._get_stored_entropy(self._get_private_key_user(index))

        while key_hex is not None and len(key_hex) > 0:
            key = ExtendedPrivateKey.from_bytes(hexstr_to_bytes(key_hex))
            if key.get_public_key().get_fingerprint() == fingerprint:
                keyring.delete_password(
                    self._get_service(), self._get_private_key_user(index)
                )
            index += 1
            key_hex = self._get_stored_entropy(self._get_private_key_user(index))

        index = 0
        seed_hex = self._get_stored_entropy(self._get_private_key_seed_user(index))
        while seed_hex is not None and len(seed_hex) > 0:
            key = ExtendedPrivateKey.from_seed(hexstr_to_bytes(seed_hex))
            if key.get_public_key().get_fingerprint() == fingerprint:
                keyring.delete_password(
                    self._get_service(), self._get_private_key_seed_user(index)
                )
            index += 1
            seed_hex = self._get_stored_entropy(self._get_private_key_seed_user(index))

    def delete_all_keys(self):
        """
        Deletes all keys from the keychain.
        """

        index = 0
        delete_exception = False
        password = None
        while True:
            try:
                password = self._get_stored_entropy(
                    self._get_private_key_seed_user(index)
                )
                keyring.delete_password(
                    self._get_service(), self._get_private_key_seed_user(index)
                )
            except BaseException:
                delete_exception = True

            # Stop when there are no more keys to delete
            if (
                password is None or len(password) == 0 or delete_exception
            ) and index > 500:
                break
            index += 1

        index = 0
        delete_exception = True
        password = None
        while True:
            try:
                password = self._get_stored_entropy(self._get_private_key_user(index))
                keyring.delete_password(
                    self._get_service(), self._get_private_key_user(index)
                )
            except BaseException:
                delete_exception = True

            # Stop when there are no more keys to delete
            if (
                password is None or len(password) == 0 or delete_exception
            ) and index > 500:
                break
            index += 1
