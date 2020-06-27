import unittest
from secrets import token_bytes
from blspy import ExtendedPrivateKey
from src.util.keychain import (
    Keychain,
    generate_mnemonic,
    bytes_from_mnemonic,
    entropy_to_seed,
)


class TesKeychain(unittest.TestCase):
    def test_basic_add_delete(self):
        kc: Keychain = Keychain(testing=True)
        kc.delete_all_keys()

        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 0
        assert kc.get_first_private_key() is None
        assert kc.get_first_public_key() is None

        mnemonic = generate_mnemonic()
        entropy = bytes_from_mnemonic(mnemonic)
        mnemonic_2 = generate_mnemonic()
        entropy_2 = bytes_from_mnemonic(mnemonic_2)

        kc.add_private_key(entropy, "")
        assert kc._get_free_private_key_index() == 1
        assert len(kc.get_all_private_keys()) == 1

        kc.add_private_key(entropy_2, "")
        kc.add_private_key(entropy_2, "")  # checks to not add duplicates
        assert kc._get_free_private_key_index() == 2
        assert len(kc.get_all_private_keys()) == 2

        assert kc._get_free_private_key_index() == 2
        assert len(kc.get_all_private_keys()) == 2
        assert len(kc.get_all_public_keys()) == 2
        assert kc.get_all_private_keys()[0] == kc.get_first_private_key()
        assert kc.get_all_public_keys()[0] == kc.get_first_public_key()

        assert len(kc.get_all_private_keys()) == 2

        seed_2 = entropy_to_seed(entropy_2, "")
        seed_key_2 = ExtendedPrivateKey.from_seed(seed_2)
        kc.delete_key_by_fingerprint(seed_key_2.get_public_key().get_fingerprint())
        assert kc._get_free_private_key_index() == 1
        assert len(kc.get_all_private_keys()) == 1

        kc.delete_all_keys()
        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 0

        kc.add_private_key(token_bytes(32), "my passphrase")
        kc.add_private_key(token_bytes(32), "")
        kc.add_private_key(token_bytes(32), "third passphrase")

        assert len(kc.get_all_public_keys()) == 3
        assert len(kc.get_all_private_keys()) == 1
        assert len(kc.get_all_private_keys(["my passphrase", ""])) == 2
        assert (
            len(
                kc.get_all_private_keys(
                    ["my passphrase", "", "third passphrase", "another"]
                )
            )
            == 3
        )
        assert len(kc.get_all_private_keys(["my passhrase wrong"])) == 0

        assert kc.get_first_private_key() is not None
        assert kc.get_first_private_key(["bad passphrase"]) is None
        assert kc.get_first_public_key() is not None

        kc.delete_all_keys()
        kc.add_private_key(token_bytes(32), "my passphrase")
        assert kc.get_first_public_key() is not None
