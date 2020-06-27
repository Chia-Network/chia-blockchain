from secrets import token_bytes
from typing import List, Tuple, Optional

import keyring as keyring_main
import pkg_resources
from bitstring import BitArray
from blspy import ExtendedPrivateKey, ExtendedPublicKey

from src.util.hash import std_hash
from sys import platform
from keyrings.cryptfile.cryptfile import CryptFileKeyring
from hashlib import pbkdf2_hmac
import unicodedata

MAX_KEYS = 100

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
    mnemonic_bytes = token_bytes(32)
    mnemonic = bytes_to_mnemonic(mnemonic_bytes)
    return mnemonic


def bytes_to_mnemonic(mnemonic_bytes: bytes):
    seed_array = bytearray(mnemonic_bytes)
    word_list = bip39_word_list().splitlines()

    checksum = bytes(std_hash(mnemonic_bytes))

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


def bytes_from_mnemonic(mnemonic: List[str]):
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


def entropy_to_seed(entropy: bytes, passphrase):
    """
    Uses BIP39 standard to derive a seed from entropy bytes.
    """
    salt_str: str = "mnemonic" + passphrase
    salt = unicodedata.normalize("NFKD", salt_str).encode("utf-8")
    seed = pbkdf2_hmac("sha512", entropy, salt, 2048)

    assert len(seed) == 64
    return seed


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

    def __init__(self, user: str = "user-1.8", testing: bool = False):
        self.testing = testing
        self.user = user

    def _get_service(self):
        """
        The keychain stores keys under a different name for tests.
        """
        if self.testing:
            return f"chia-{self.user}-test"
        else:
            return f"chia-{self.user}"

    def _get_pk_and_entropy(
        self, user: str
    ) -> Optional[Tuple[ExtendedPublicKey, bytes]]:
        """
        Returns the keychain conntents for a specific 'user' (key index). The contents
        include an ExtendedPublicKey and the entropy required to generate the private key.
        Note that generating the actual private key also requires the passphrase.
        """
        epks = ExtendedPublicKey.EXTENDED_PUBLIC_KEY_SIZE
        read_str = keyring.get_password(self._get_service(), user)
        if read_str is None or len(read_str) == 0:
            return None
        str_bytes = bytes.fromhex(read_str)
        return (ExtendedPublicKey.from_bytes(str_bytes[:epks]), str_bytes[epks:])

    def _get_private_key_user(self, index: int):
        """
        Returns the keychain user string for a key index.
        """
        if self.testing:
            return f"wallet-{self.user}-test-{index}"
        else:
            return f"wallet-{self.user}-{index}"

            return f"wallet-{self.user}-raw-{index}"

    def _get_free_private_key_index(self) -> int:
        """
        Get the index of the first free spot  in the keychain.
        """
        index = 0
        while True:
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
            if pkent is None:
                return index
            index += 1

    def add_private_key(self, entropy: bytes, passphrase: str) -> ExtendedPrivateKey:
        """
        Adds a private key to the keychain, with the given entropy and passphrase. The
        keychain itself will store the extended public key, and the entropy bytes,
        but not the passphrase.
        """
        seed = entropy_to_seed(entropy, passphrase)
        index = self._get_free_private_key_index()
        key = ExtendedPrivateKey.from_seed(seed)
        fingerprint = key.get_public_key().get_fingerprint()
        if fingerprint in [
            epk.get_public_key().get_fingerprint() for epk in self.get_all_public_keys()
        ]:
            # Prevents duplicate add
            return key

        keyring.set_password(
            self._get_service(),
            self._get_private_key_user(index),
            bytes(key.get_extended_public_key()).hex() + entropy.hex(),
        )
        return key

    def get_first_private_key(
        self, passphrases: List[str] = [""]
    ) -> Optional[Tuple[ExtendedPrivateKey, Optional[bytes]]]:
        """
        Returns the first key in the keychain that has one of the passed in passphrases.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                epk, ent = pkent
                for pp in passphrases:
                    seed = entropy_to_seed(ent, pp)
                    key = ExtendedPrivateKey.from_seed(seed)
                    if key.get_extended_public_key() == epk:
                        return (key, ent)
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        return None

    def get_all_private_keys(
        self, passphrases: List[str] = [""]
    ) -> List[Tuple[ExtendedPrivateKey, bytes]]:
        """
        Returns all private keys which can be retrieved, with the given passphrases.
        A tuple of key, and entropy bytes (i.e. mnemonic) is returned for each key.
        """
        all_keys: List[Tuple[ExtendedPrivateKey, bytes]] = []

        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                epk, ent = pkent
                for pp in passphrases:
                    seed = entropy_to_seed(ent, pp)
                    key = ExtendedPrivateKey.from_seed(seed)
                    if key.get_extended_public_key() == epk:
                        all_keys.append((key, ent))
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        return all_keys

    def get_all_public_keys(self) -> List[ExtendedPublicKey]:
        """
        Returns all extended public keys.
        """
        all_keys: List[Tuple[ExtendedPublicKey, bytes]] = []

        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                epk, ent = pkent
                all_keys.append(epk)
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        return all_keys

    def get_first_public_key(self) -> Optional[ExtendedPublicKey]:
        """
        Returns the first extended public key.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                epk, ent = pkent
                return epk
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
                epk, ent = pkent
                if epk.get_public_key().get_fingerprint() == fingerprint:
                    keyring.delete_password(
                        self._get_service(), self._get_private_key_user(index)
                    )
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
                keyring.delete_password(
                    self._get_service(), self._get_private_key_user(index)
                )
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
                pkent = self._get_fingerprint_and_entropy(
                    self._get_private_key_user(index)
                )
                keyring.delete_password(
                    self._get_service(), self._get_private_key_user(index)
                )
            except Exception:
                # Some platforms might throw on no existing key
                delete_exception = True

            # Stop when there are no more keys to delete
            if (pkent is None or delete_exception) and index > MAX_KEYS:
                break
            index += 1
