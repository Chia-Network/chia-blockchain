import unittest
from blspy import ExtendedPrivateKey
from src.util.keychain import Keychain, generate_mnemonic, seed_from_mnemonic


class TesKeychain(unittest.TestCase):
    def test_basic_add_delete(self):
        kc: Keychain = Keychain(testing=True)
        kc.delete_all_keys()

        assert kc._get_free_private_key_seed_index() == 0
        assert len(kc.get_all_private_keys()) == 0
        assert kc.get_first_private_key() is None
        assert kc.get_first_public_key() is None

        mnemonic = generate_mnemonic()
        seed = seed_from_mnemonic(mnemonic)
        mnemonic_2 = generate_mnemonic()
        seed_2 = seed_from_mnemonic(mnemonic_2)

        kc.add_private_key_seed(seed)
        assert kc._get_free_private_key_seed_index() == 1
        assert len(kc.get_all_private_keys()) == 1

        kc.add_private_key_seed(seed_2)
        kc.add_private_key_seed(seed_2)  # checks to not add duplicates
        assert kc._get_free_private_key_seed_index() == 2
        assert len(kc.get_all_private_keys()) == 2

        assert kc._get_free_private_key_seed_index() == 2
        assert len(kc.get_all_private_keys()) == 2
        assert len(kc.get_all_public_keys()) == 2
        assert kc.get_all_private_keys()[0] == kc.get_first_private_key()
        assert kc.get_all_public_keys()[0] == kc.get_first_public_key()

        assert len(kc.get_all_private_keys()) == 2

        seed_key_2 = ExtendedPrivateKey.from_seed(seed_2)
        kc.delete_key_by_fingerprint(seed_key_2.get_public_key().get_fingerprint())
        assert kc._get_free_private_key_seed_index() == 1
        assert len(kc.get_all_private_keys()) == 1

        kc.delete_all_keys()
        assert kc._get_free_private_key_seed_index() == 0
        assert len(kc.get_all_private_keys()) == 0
