import unicodedata

from secrets import token_bytes
from sys import platform
from typing import List, Tuple, Optional
from hashlib import pbkdf2_hmac

import keyring as keyring_main
import pkg_resources

from bitstring import BitArray
from blspy import PrivateKey, G1Element
from keyrings.cryptfile.cryptfile import CryptFileKeyring
from src.util.hash import std_hash


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
    The keychain stores two types of keys: private keys, which are PrivateKeys from blspy,
    and private key seeds, which are bytes objects that are used as a seed to construct
    PrivateKeys. Private key seeds are converted to mnemonics when shown to users.

    Both types of keys are stored as hex strings in the python keyring, and the implementation of
    the keyring depends on OS. Both types of keys can be added, and get_private_keys returns a
    list of all keys.
    """

    testing: bool
    user: str

    def __init__(self, user: str = "user-1.8.0", testing: bool = False):
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

    def _get_pk_and_entropy(self, user: str) -> Optional[Tuple[G1Element, bytes]]:
        """
        Returns the keychain conntents for a specific 'user' (key index). The contents
        include an G1Element and the entropy required to generate the private key.
        Note that generating the actual private key also requires the passphrase.
        """
        read_str = keyring.get_password(self._get_service(), user)
        if read_str is None or len(read_str) == 0:
            return None
        str_bytes = bytes.fromhex(read_str)
        return (
            G1Element.from_bytes(str_bytes[: G1Element.SIZE]),
            str_bytes[G1Element.SIZE :],
        )

    def _get_private_key_user(self, index: int):
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

    def add_private_key(self, entropy: bytes, passphrase: str) -> PrivateKey:
        """
        Adds a private key to the keychain, with the given entropy and passphrase. The
        keychain itself will store the public key, and the entropy bytes,
        but not the passphrase.
        """
        seed = entropy_to_seed(entropy, passphrase)
        index = self._get_free_private_key_index()
        key = PrivateKey.from_seed(seed)
        fingerprint = key.get_g1().get_fingerprint()

        if fingerprint in [pk.get_fingerprint() for pk in self.get_all_public_keys()]:
            # Prevents duplicate add
            return key

        keyring.set_password(
            self._get_service(),
            self._get_private_key_user(index),
            bytes(key.get_g1()).hex() + entropy.hex(),
        )
        return key

    def get_first_private_key(
        self, passphrases: List[str] = [""]
    ) -> Optional[Tuple[PrivateKey, bytes]]:
        """
        Returns the first key in the keychain that has one of the passed in passphrases.
        """
        index = 0
        pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        while index <= MAX_KEYS:
            if pkent is not None:
                pk, ent = pkent
                for pp in passphrases:
                    seed = entropy_to_seed(ent, pp)
                    key = PrivateKey.from_seed(seed)
                    if key.get_g1() == pk:
                        return (key, ent)
            index += 1
            pkent = self._get_pk_and_entropy(self._get_private_key_user(index))
        return None

    def get_all_private_keys(
        self, passphrases: List[str] = [""]
    ) -> List[Tuple[PrivateKey, bytes]]:
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
                    seed = entropy_to_seed(ent, pp)
                    key = PrivateKey.from_seed(seed)
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
                pkent = self._get_pk_and_entropy(
                    self._get_private_key_user(index)
                )  # changed from _get_fingerprint_and_entropy to _get_pk_and_entropy - GH
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
