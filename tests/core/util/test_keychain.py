import json
import unittest
from secrets import token_bytes

from blspy import AugSchemeMPL, PrivateKey

from tests.util.keyring import using_temp_file_keyring
from chia.util.keychain import Keychain, bytes_from_mnemonic, bytes_to_mnemonic, generate_mnemonic, mnemonic_to_seed


class TestKeychain(unittest.TestCase):
    @using_temp_file_keyring()
    def test_basic_add_delete(self):
        kc: Keychain = Keychain(user="testing-1.8.0", service="chia-testing-1.8.0")
        kc.delete_all_keys()

        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 0
        assert kc.get_first_private_key() is None
        assert kc.get_first_public_key() is None

        mnemonic = generate_mnemonic()
        entropy = bytes_from_mnemonic(mnemonic)
        assert bytes_to_mnemonic(entropy) == mnemonic
        mnemonic_2 = generate_mnemonic()

        # misspelled words in the mnemonic
        bad_mnemonic = mnemonic.split(" ")
        bad_mnemonic[6] = "ZZZZZZ"
        self.assertRaisesRegex(
            ValueError,
            "'ZZZZZZ' is not in the mnemonic dictionary; may be misspelled",
            bytes_from_mnemonic,
            " ".join(bad_mnemonic),
        )

        kc.add_private_key(mnemonic)
        assert kc._get_free_private_key_index() == 1
        assert len(kc.get_all_private_keys()) == 1

        kc.add_private_key(mnemonic_2)
        kc.add_private_key(mnemonic_2)  # checks to not add duplicates
        assert kc._get_free_private_key_index() == 2
        assert len(kc.get_all_private_keys()) == 2

        assert kc._get_free_private_key_index() == 2
        assert len(kc.get_all_private_keys()) == 2
        assert len(kc.get_all_public_keys()) == 2
        assert kc.get_all_private_keys()[0] == kc.get_first_private_key()
        assert kc.get_all_public_keys()[0] == kc.get_first_public_key()

        assert len(kc.get_all_private_keys()) == 2

        seed_2 = mnemonic_to_seed(mnemonic)
        seed_key_2 = AugSchemeMPL.key_gen(seed_2)
        kc.delete_key_by_fingerprint(seed_key_2.get_g1().get_fingerprint())
        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 1

        kc.delete_all_keys()
        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 0

        kc.add_private_key(bytes_to_mnemonic(token_bytes(32)))
        kc.add_private_key(bytes_to_mnemonic(token_bytes(32)))
        kc.add_private_key(bytes_to_mnemonic(token_bytes(32)))

        assert len(kc.get_all_public_keys()) == 3

        assert kc.get_first_private_key() is not None
        assert kc.get_first_public_key() is not None

        kc.delete_all_keys()
        kc.add_private_key(bytes_to_mnemonic(token_bytes(32)))
        assert kc.get_first_public_key() is not None

    @using_temp_file_keyring()
    def test_bip39_eip2333_test_vector(self):
        kc: Keychain = Keychain(user="testing-1.8.0", service="chia-testing-1.8.0")
        kc.delete_all_keys()

        mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        print("entropy to seed:", mnemonic_to_seed(mnemonic).hex())
        master_sk = kc.add_private_key(mnemonic)
        tv_master_int = 8075452428075949470768183878078858156044736575259233735633523546099624838313
        tv_child_int = 18507161868329770878190303689452715596635858303241878571348190917018711023613
        assert master_sk == PrivateKey.from_bytes(tv_master_int.to_bytes(32, "big"))
        child_sk = AugSchemeMPL.derive_child_sk(master_sk, 0)
        assert child_sk == PrivateKey.from_bytes(tv_child_int.to_bytes(32, "big"))

    def test_bip39_test_vectors(self):
        with open("tests/util/bip39_test_vectors.json") as f:
            all_vectors = json.loads(f.read())

        for vector_list in all_vectors["english"]:
            entropy_bytes = bytes.fromhex(vector_list[0])
            mnemonic = vector_list[1]
            seed = bytes.fromhex(vector_list[2])

            assert bytes_from_mnemonic(mnemonic) == entropy_bytes
            assert bytes_to_mnemonic(entropy_bytes) == mnemonic
            assert mnemonic_to_seed(mnemonic) == seed

    def test_utf8_nfkd(self):
        # Test code from trezor:
        # Copyright (c) 2013 Pavol Rusnak
        # Copyright (c) 2017 mruddy
        # https://github.com/trezor/python-mnemonic/blob/master/test_mnemonic.py
        # The same sentence in various UTF-8 forms
        words_nfkd = "Pr\u030ci\u0301s\u030cerne\u030c z\u030clut\u030couc\u030cky\u0301 ku\u030an\u030c u\u0301pe\u030cl d\u030ca\u0301belske\u0301 o\u0301dy za\u0301ker\u030cny\u0301 uc\u030cen\u030c be\u030cz\u030ci\u0301 pode\u0301l zo\u0301ny u\u0301lu\u030a"  # noqa: E501
        words_nfc = "P\u0159\xed\u0161ern\u011b \u017elu\u0165ou\u010dk\xfd k\u016f\u0148 \xfap\u011bl \u010f\xe1belsk\xe9 \xf3dy z\xe1ke\u0159n\xfd u\u010de\u0148 b\u011b\u017e\xed pod\xe9l z\xf3ny \xfal\u016f"  # noqa: E501
        words_nfkc = "P\u0159\xed\u0161ern\u011b \u017elu\u0165ou\u010dk\xfd k\u016f\u0148 \xfap\u011bl \u010f\xe1belsk\xe9 \xf3dy z\xe1ke\u0159n\xfd u\u010de\u0148 b\u011b\u017e\xed pod\xe9l z\xf3ny \xfal\u016f"  # noqa: E501
        words_nfd = "Pr\u030ci\u0301s\u030cerne\u030c z\u030clut\u030couc\u030cky\u0301 ku\u030an\u030c u\u0301pe\u030cl d\u030ca\u0301belske\u0301 o\u0301dy za\u0301ker\u030cny\u0301 uc\u030cen\u030c be\u030cz\u030ci\u0301 pode\u0301l zo\u0301ny u\u0301lu\u030a"  # noqa: E501

        seed_nfkd = mnemonic_to_seed(words_nfkd)
        seed_nfc = mnemonic_to_seed(words_nfc)
        seed_nfkc = mnemonic_to_seed(words_nfkc)
        seed_nfd = mnemonic_to_seed(words_nfd)

        assert seed_nfkd == seed_nfc
        assert seed_nfkd == seed_nfkc
        assert seed_nfkd == seed_nfd
