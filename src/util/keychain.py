import bisect
from secrets import token_bytes
from typing import List, Optional

import keyring
import pkg_resources
from bitstring import BitArray

from src.types.sized_bytes import bytes32
from src.util.byte_types import hexstr_to_bytes
from src.util.hash import std_hash


def binary_search(a, x, lo=0, hi=None):
    hi = hi if hi is not None else len(a)
    pos = bisect.bisect_left(a, x, lo, hi)
    return pos if pos != hi and a[pos] == x else -1


def bip39_word_list() -> str:
    return pkg_resources.resource_string("src.util.bip39", f"english.txt").decode()


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
    word_list = bip39_word_list().splitlines()
    bit_array = BitArray()
    for i in range(0, 24):
        word = mnemonic[i]
        value = binary_search(word_list, word)
        if value == -1:
            raise ValueError(f"{word} not in mnemonic list")

        bit_array.append(BitArray(uint=value, length=11))

    all_bytes = bit_array.bytes
    entropy_bytes = all_bytes[:32]
    checksum_bytes = all_bytes[32]
    checksum = std_hash(entropy_bytes)

    if checksum[0] != checksum_bytes:
        raise ValueError(f"Invalid order of mnemonic words")

    return entropy_bytes


class Keychain:
    testing: bool

    @staticmethod
    def create(testing: bool):
        self = Keychain()
        self.testing = testing
        return self

    def get_service(self):
        if self.testing:
            return "chia-test"
        else:
            return "chia"

    def get_wallet_user(self):
        if self.testing:
            return "wallet-test"
        else:
            return "wallet"

    def get_harvester_user(self):
        if self.testing:
            return "harvester-test"
        else:
            return "harvester"

    def get_pool_user(self):
        if self.testing:
            return "pool-test"
        else:
            return "pool"

    def set_wallet_seed(self, seed: bytes):
        keyring.set_password(self.get_service(), self.get_wallet_user(), seed.hex())

    def get_stored_entropy(self, user: str):
        return keyring.get_password(self.get_service(), user)

    def get_wallet_seed(self) -> Optional[bytes32]:
        seed = self.get_stored_entropy(self.get_wallet_user())
        if seed is None:
            return None
        return hexstr_to_bytes(seed)

    def delete_all_keys(self):
        keyring.delete_password(self.get_service(), self.get_wallet_user())
        keyring.delete_password(self.get_service(), self.get_pool_user())
        keyring.delete_password(self.get_service(), self.get_harvester_user())

    def get_harvester_seed(self) -> Optional[bytes32]:
        stored = self.get_stored_entropy(self.get_harvester_user())
        if stored is not None:
            return stored

        wallet_seed = self.get_wallet_seed()
        if wallet_seed is None:
            return None
        default_harvester = std_hash(wallet_seed)
        return default_harvester

    def set_harvested_seed(self, seed):
        keyring.set_password(self.get_service(), self.get_harvester_user(), seed.hex())

    def get_pool_seed(self) -> Optional[bytes32]:
        stored = self.get_stored_entropy(self.get_pool_user())
        if stored is not None:
            return stored

        wallet_seed = self.get_wallet_seed()
        if wallet_seed is None:
            return None

        default_pool = std_hash(std_hash(wallet_seed))
        return default_pool

    def set_pool_seed(self, seed):
        keyring.set_password(self.get_service(), self.get_pool_user(), seed.hex())
