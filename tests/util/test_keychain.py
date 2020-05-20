import unittest
from blspy import ExtendedPrivateKey
from src.util.keychain import Keychain, generate_mnemonic, seed_from_mnemonic


class TesKeychain(unittest.TestCase):
    def test_basic_add_delete(self):
        kc: Keychain = Keychain(testing=True)
        kc.delete_all_keys()

        assert kc._get_free_private_key_seed_index() == 0
        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 0

        mnemonic = generate_mnemonic()
        seed = seed_from_mnemonic(mnemonic)
        mnemonic_2 = generate_mnemonic()
        seed_2 = seed_from_mnemonic(mnemonic_2)

        kc.add_private_key_seed(seed)
        assert kc._get_free_private_key_seed_index() == 1
        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 1

        kc.add_private_key_seed(seed_2)
        kc.add_private_key_seed(seed_2)  # checks to not add duplicates
        assert kc._get_free_private_key_seed_index() == 2
        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 2

        raw = ExtendedPrivateKey.from_seed(b"123")
        kc.add_private_key(raw)
        kc.add_private_key(raw)
        kc.add_private_key(raw)
        kc.add_private_key(raw)  # Checks to not add duplicates
        raw_2 = ExtendedPrivateKey.from_seed(b"1234")
        kc.add_private_key(raw_2)

        assert kc._get_free_private_key_seed_index() == 2
        assert kc._get_free_private_key_index() == 2
        assert len(kc.get_all_private_keys()) == 4
        assert len(kc.get_all_public_keys()) == 4
        assert raw in [k for (k, s) in kc.get_all_private_keys()]

        kc.delete_key_by_fingerprint(raw_2.get_public_key().get_fingerprint())
        assert kc._get_free_private_key_index() == 1
        assert len(kc.get_all_private_keys()) == 3

        seed_key_2 = ExtendedPrivateKey.from_seed(seed_2)
        kc.delete_key_by_fingerprint(seed_key_2.get_public_key().get_fingerprint())
        assert kc._get_free_private_key_seed_index() == 1
        assert len(kc.get_all_private_keys()) == 2

        kc.delete_all_keys()
        assert kc._get_free_private_key_seed_index() == 0
        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 0

        kc.add_private_key_not_extended(raw_2.get_private_key())
        assert kc._get_free_private_key_seed_index() == 0
        assert kc._get_free_private_key_index() == 1
        assert len(kc.get_all_private_keys()) == 1
        assert raw_2 not in [k for (k, s) in kc.get_all_private_keys()]
        assert raw_2.get_private_key() in [
            k.get_private_key() for (k, s) in kc.get_all_private_keys()
        ]
