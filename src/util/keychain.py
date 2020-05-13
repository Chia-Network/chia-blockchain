import bisect
from secrets import token_bytes
from typing import List, Optional

import keyring
import pkg_resources
from bitstring import BitArray
from blspy import ExtendedPrivateKey, PrivateKey
from src.consensus.coinbase import create_puzzlehash_for_pk

from src.types.BLSSignature import BLSPublicKey

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
    user: str

    @staticmethod
    def create(user: str = "user", testing: bool = False):
        self = Keychain()
        self.testing = testing
        self.user = user
        return self

    def get_service(self):
        if self.testing:
            return f"chia-{self.user}-test"
        else:
            return f"chia-{self.user}"

    def get_wallet_user(self):
        if self.testing:
            return f"wallet-{self.user}-test"
        else:
            return f"wallet-{self.user}"

    def get_harvester_user(self):
        if self.testing:
            return f"harvester-{self.user}-test"
        else:
            return f"harvester-{self.user}"

    def get_pool_user(self):
        if self.testing:
            return f"pool-{self.user}-test"
        else:
            return f"pool-{self.user}"

    def get_pool_user_raw(self, index: int):
        """ This should be used to store whole key, not entropy"""
        if self.testing:
            return f"pool-{self.user}-test-raw-{index}"
        else:
            return f"pool-{self.user}-raw-{index}"

    def get_pool_target_user(self):
        if self.testing:
            return f"pool-{self.user}-target-test"
        else:
            return f"pool-{self.user}-target"

    def get_wallet_target_user(self):
        if self.testing:
            return f"wallet-{self.user}-target-test"
        else:
            return f"wallet-{self.user}-target"

    def get_plot_user(self):
        if self.testing:
            return f"plot-{self.user}-test"
        else:
            return f"plot-{self.user}"

    def set_wallet_seed(self, seed: bytes):
        keyring.set_password(self.get_service(), self.get_wallet_user(), seed.hex())

    def get_stored_entropy(self, user: str):
        return keyring.get_password(self.get_service(), user)

    def get_wallet_seed(self) -> Optional[bytes32]:
        seed = self.get_stored_entropy(self.get_wallet_user())
        if seed is None:
            return None
        return hexstr_to_bytes(seed)

    def get_wallet_key(self) -> Optional[ExtendedPrivateKey]:
        wallet_seed = self.get_wallet_seed()
        if wallet_seed is None:
            return None

        wallet_sk = ExtendedPrivateKey.from_seed(wallet_seed)
        return wallet_sk

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
            return hexstr_to_bytes(stored)

        wallet_seed = self.get_wallet_seed()
        if wallet_seed is None:
            return None

        default_pool = std_hash(std_hash(wallet_seed))
        return default_pool

    def get_pool_keys(self) -> List[PrivateKey]:
        raw_keys = self.get_pool_keys_raw()
        if len(raw_keys) == 2:
            return raw_keys
        pool_seed = self.get_pool_seed()
        if pool_seed is None:
            return []
        key_one = PrivateKey.from_seed(pool_seed)
        key_two = PrivateKey.from_seed(std_hash(pool_seed))
        return [key_one, key_two]

    def set_pool_seed(self, seed):
        keyring.set_password(self.get_service(), self.get_pool_user(), seed.hex())

    def get_wallet_target(self) -> Optional[bytes32]:
        stored = self.get_stored_entropy(self.get_wallet_target_user())
        if stored is not None:
            return hexstr_to_bytes(stored)

        wallet_seed = self.get_wallet_seed()
        if wallet_seed is None:
            return None

        wallet_sk = ExtendedPrivateKey.from_seed(wallet_seed)
        wallet_pk = wallet_sk.public_child(0).get_public_key()
        wallet_target = create_puzzlehash_for_pk(BLSPublicKey(bytes(wallet_pk)))
        return wallet_target

    def get_pool_target(self) -> Optional[bytes32]:
        stored = self.get_stored_entropy(self.get_pool_target_user())
        if stored is not None:
            return hexstr_to_bytes(stored)

        wallet_seed = self.get_wallet_seed()
        if wallet_seed is None:
            return None

        wallet_sk = ExtendedPrivateKey.from_seed(wallet_seed)
        wallet_pk = wallet_sk.public_child(0).get_public_key()
        wallet_target = create_puzzlehash_for_pk(BLSPublicKey(bytes(wallet_pk)))
        return wallet_target

    def set_pool_target(self, target: bytes32):
        keyring.set_password(
            self.get_service(), self.get_pool_target_user(), target.hex()
        )

    def set_wallet_target(self, target: bytes32):
        keyring.set_password(
            self.get_service(), self.get_wallet_target_user(), target.hex()
        )

    def set_pool_key_raw(self, key_0: bytes, key_1: bytes):
        keyring.set_password(self.get_service(), self.get_pool_user_raw(0), key_0.hex())
        keyring.set_password(self.get_service(), self.get_pool_user_raw(0), key_1.hex())

    def get_pool_keys_raw(self) -> List[PrivateKey]:
        raw_0 = keyring.get_password(self.get_service(), self.get_pool_user_raw(0))
        raw_1 = keyring.get_password(self.get_service(), self.get_pool_user_raw(1))

        if raw_0 is None or raw_1 is None:
            return []
        else:
            key_0 = PrivateKey.from_bytes(hexstr_to_bytes(raw_0))
            key_1 = PrivateKey.from_bytes(hexstr_to_bytes(raw_1))
            return [key_0, key_1]

    def get_plot_seed(self):
        stored = self.get_stored_entropy(self.get_plot_user())
        if stored is not None:
            return stored

        wallet_seed = self.get_wallet_seed()
        if wallet_seed is None:
            return None

        default_pool = std_hash(std_hash(std_hash(wallet_seed)))
        return default_pool

    def safe_delete(self, service: str, user: str):
        try:
            keyring.delete_password(service, user)
        except BaseException:
            pass

    def delete_all_keys(self):
        self.safe_delete(self.get_service(), self.get_wallet_user())
        self.safe_delete(self.get_service(), self.get_wallet_target_user())
        self.safe_delete(self.get_service(), self.get_pool_user_raw(0))
        self.safe_delete(self.get_service(), self.get_pool_user_raw(1))
        self.safe_delete(self.get_service(), self.get_pool_user())
        self.safe_delete(self.get_service(), self.get_pool_target_user())
        self.safe_delete(self.get_service(), self.get_harvester_user())
        self.safe_delete(self.get_service(), self.get_plot_user())
