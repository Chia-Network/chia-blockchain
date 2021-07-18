import json
import unittest
from secrets import token_bytes

from blspy import AugSchemeMPL, PrivateKey

from chives.util.keychain import Keychain, bytes_from_mnemonic, bytes_to_mnemonic, generate_mnemonic, mnemonic_to_seed


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

        kc.add_private_key(mnemonic, "")
        assert kc._get_free_private_key_index() == 1
        assert len(kc.get_all_private_keys()) == 1

        kc.add_private_key(mnemonic_2, "")
        kc.add_private_key(mnemonic_2, "")  # checks to not add duplicates
        assert kc._get_free_private_key_index() == 2
        assert len(kc.get_all_private_keys()) == 2

        assert kc._get_free_private_key_index() == 2
        assert len(kc.get_all_private_keys()) == 2
        assert len(kc.get_all_public_keys()) == 2
        assert kc.get_all_private_keys()[0] == kc.get_first_private_key()
        assert kc.get_all_public_keys()[0] == kc.get_first_public_key()

        assert len(kc.get_all_private_keys()) == 2

        seed_2 = mnemonic_to_seed(mnemonic, "")
        seed_key_2 = AugSchemeMPL.key_gen(seed_2)
        kc.delete_key_by_fingerprint(seed_key_2.get_g1().get_fingerprint())
        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 1

        kc.delete_all_keys()
        assert kc._get_free_private_key_index() == 0
        assert len(kc.get_all_private_keys()) == 0

        kc.add_private_key(bytes_to_mnemonic(token_bytes(32)), "my passphrase")
        kc.add_private_key(bytes_to_mnemonic(token_bytes(32)), "")
        kc.add_private_key(bytes_to_mnemonic(token_bytes(32)), "third passphrase")

        assert len(kc.get_all_public_keys()) == 3
        assert len(kc.get_all_private_keys()) == 1
        assert len(kc.get_all_private_keys(["my passphrase", ""])) == 2
        assert len(kc.get_all_private_keys(["my passphrase", "", "third passphrase", "another"])) == 3
        assert len(kc.get_all_private_keys(["my passhrase wrong"])) == 0

        assert kc.get_first_private_key() is not None
        assert kc.get_first_private_key(["bad passphrase"]) is None
        assert kc.get_first_public_key() is not None

        kc.delete_all_keys()
        kc.add_private_key(bytes_to_mnemonic(token_bytes(32)), "my passphrase")
        assert kc.get_first_public_key() is not None

    def test_bip39_eip2333_test_vector(self):
        kc: Keychain = Keychain(testing=True)
        kc.delete_all_keys()

        mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
        passphrase = "TREZOR"
        print("entropy to seed:", mnemonic_to_seed(mnemonic, passphrase).hex())
        master_sk = kc.add_private_key(mnemonic, passphrase)
        tv_master_int = 5399117110774477986698372024995405256382522670366369834617409486544348441851
        tv_child_int = 11812940737387919040225825939013910852517748782307378293770044673328955938106
        assert master_sk == PrivateKey.from_bytes(tv_master_int.to_bytes(32, "big"))
        child_sk = AugSchemeMPL.derive_child_sk(master_sk, 0)
        assert child_sk == PrivateKey.from_bytes(tv_child_int.to_bytes(32, "big"))

    def test_bip39_test_vectors_trezor(self):
        with open("tests/util/bip39_test_vectors.json") as f:
            all_vectors = json.loads(f.read())

        for vector_list in all_vectors["english"]:
            entropy_bytes = bytes.fromhex(vector_list[0])
            mnemonic = vector_list[1]
            seed = bytes.fromhex(vector_list[2])

            assert bytes_from_mnemonic(mnemonic) == entropy_bytes
            assert bytes_to_mnemonic(entropy_bytes) == mnemonic
            assert mnemonic_to_seed(mnemonic, "TREZOR") == seed

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

        passphrase_nfkd = "Neuve\u030cr\u030citelne\u030c bezpec\u030cne\u0301 hesli\u0301c\u030cko"
        passphrase_nfc = "Neuv\u011b\u0159iteln\u011b bezpe\u010dn\xe9 hesl\xed\u010dko"
        passphrase_nfkc = "Neuv\u011b\u0159iteln\u011b bezpe\u010dn\xe9 hesl\xed\u010dko"
        passphrase_nfd = "Neuve\u030cr\u030citelne\u030c bezpec\u030cne\u0301 hesli\u0301c\u030cko"

        seed_nfkd = mnemonic_to_seed(words_nfkd, passphrase_nfkd)
        seed_nfc = mnemonic_to_seed(words_nfc, passphrase_nfc)
        seed_nfkc = mnemonic_to_seed(words_nfkc, passphrase_nfkc)
        seed_nfd = mnemonic_to_seed(words_nfd, passphrase_nfd)

        assert seed_nfkd == seed_nfc
        assert seed_nfkd == seed_nfkc
        assert seed_nfkd == seed_nfd


if __name__ == "__main__":
    unittest.main()
