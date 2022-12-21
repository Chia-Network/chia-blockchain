from __future__ import annotations

import json
import unittest
from dataclasses import replace
from secrets import token_bytes
from typing import Callable, List, Optional, Tuple

import pytest
from blspy import AugSchemeMPL, G1Element, PrivateKey

from chia.simulator.keyring import using_temp_file_keyring
from chia.util.errors import (
    KeychainFingerprintExists,
    KeychainFingerprintNotFound,
    KeychainKeyDataMismatch,
    KeychainLabelExists,
    KeychainLabelInvalid,
    KeychainSecretsMissing,
)
from chia.util.ints import uint32
from chia.util.keychain import (
    Keychain,
    KeyData,
    KeyDataSecrets,
    bytes_from_mnemonic,
    bytes_to_mnemonic,
    generate_mnemonic,
    mnemonic_to_seed,
)

mnemonic = (
    "rapid this oven common drive ribbon bulb urban uncover napkin kitten usage enforce uncle unveil scene "
    "apart wire mystery torch peanut august flee fantasy"
)
entropy = bytes.fromhex("b1fc1a7717343572077f7aecb25ded77c4a3d93b9e040a5f8649f2aa1e1e5632")
private_key = PrivateKey.from_bytes(bytes.fromhex("6c6bb4cc3dae03b8d0b327dd6765834464a883f7ca7df134970842055efe8afc"))
fingerprint = uint32(1310648153)
public_key = G1Element.from_bytes(
    bytes.fromhex("b5acf3599bc5fa5da1c00f6cc3d5bcf1560def67778b7f50a8c373a83f78761505b6250ab776e38a292e26628009aec4")
)


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
        fingerprint_2 = AugSchemeMPL.key_gen(mnemonic_to_seed(mnemonic_2)).get_g1().get_fingerprint()

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
        with pytest.raises(KeychainFingerprintExists) as e:
            kc.add_private_key(mnemonic_2)
        assert e.value.fingerprint == fingerprint_2
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
    def test_add_private_key_label(self):
        keychain: Keychain = Keychain(user="testing-1.8.0", service="chia-testing-1.8.0")

        key_data_0 = KeyData.generate(label="key_0")
        key_data_1 = KeyData.generate(label="key_1")
        key_data_2 = KeyData.generate(label=None)

        keychain.add_private_key(mnemonic=key_data_0.mnemonic_str(), label=key_data_0.label)
        assert key_data_0 == keychain.get_key(key_data_0.fingerprint, include_secrets=True)

        # Try to add a new key with an existing label should raise
        with pytest.raises(KeychainLabelExists) as e:
            keychain.add_private_key(mnemonic=key_data_1.mnemonic_str(), label=key_data_0.label)
        assert e.value.fingerprint == key_data_0.fingerprint
        assert e.value.label == key_data_0.label

        # Adding the same key with a valid label should work fine
        keychain.add_private_key(mnemonic=key_data_1.mnemonic_str(), label=key_data_1.label)
        assert key_data_1 == keychain.get_key(key_data_1.fingerprint, include_secrets=True)

        # Trying to add an existing key should not have an impact on the existing label
        with pytest.raises(KeychainFingerprintExists):
            keychain.add_private_key(mnemonic=key_data_0.mnemonic_str(), label="other label")
        assert key_data_0 == keychain.get_key(key_data_0.fingerprint, include_secrets=True)

        # Adding a key with no label should not assign any label
        keychain.add_private_key(mnemonic=key_data_2.mnemonic_str(), label=key_data_2.label)
        assert key_data_2 == keychain.get_key(key_data_2.fingerprint, include_secrets=True)

        # All added keys should still be valid with their label
        assert all(
            key_data in [key_data_0, key_data_1, key_data_2] for key_data in keychain.get_keys(include_secrets=True)
        )

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


def test_key_data_secrets_generate() -> None:
    secrets = KeyDataSecrets.generate()
    assert secrets.private_key == AugSchemeMPL.key_gen(mnemonic_to_seed(secrets.mnemonic_str()))
    assert secrets.entropy == bytes_from_mnemonic(secrets.mnemonic_str())


@pytest.mark.parametrize(
    "input_data, from_method", [(mnemonic, KeyDataSecrets.from_mnemonic), (entropy, KeyDataSecrets.from_entropy)]
)
def test_key_data_secrets_creation(input_data: object, from_method: Callable[..., KeyDataSecrets]) -> None:
    secrets = from_method(input_data)
    assert secrets.mnemonic == mnemonic.split()
    assert secrets.mnemonic_str() == mnemonic
    assert secrets.entropy == entropy
    assert secrets.private_key == private_key


@pytest.mark.parametrize("label", [None, "key"])
def test_key_data_generate(label: Optional[str]) -> None:
    key_data = KeyData.generate(label)
    assert key_data.private_key == AugSchemeMPL.key_gen(mnemonic_to_seed(key_data.mnemonic_str()))
    assert key_data.entropy == bytes_from_mnemonic(key_data.mnemonic_str())
    assert key_data.public_key == key_data.private_key.get_g1()
    assert key_data.fingerprint == key_data.private_key.get_g1().get_fingerprint()
    assert key_data.label == label


@pytest.mark.parametrize("label", [None, "key"])
@pytest.mark.parametrize(
    "input_data, from_method", [(mnemonic, KeyData.from_mnemonic), (entropy, KeyData.from_entropy)]
)
def test_key_data_creation(input_data: object, from_method: Callable[..., KeyData], label: Optional[str]) -> None:
    key_data = from_method(input_data, label)
    assert key_data.fingerprint == fingerprint
    assert key_data.public_key == public_key
    assert key_data.mnemonic == mnemonic.split()
    assert key_data.mnemonic_str() == mnemonic
    assert key_data.entropy == entropy
    assert key_data.private_key == private_key
    assert key_data.label == label


def test_key_data_without_secrets() -> None:
    key_data = KeyData(fingerprint, public_key, None, None)
    assert key_data.secrets is None

    with pytest.raises(KeychainSecretsMissing):
        print(key_data.mnemonic)

    with pytest.raises(KeychainSecretsMissing):
        print(key_data.mnemonic_str())

    with pytest.raises(KeychainSecretsMissing):
        print(key_data.entropy)

    with pytest.raises(KeychainSecretsMissing):
        print(key_data.private_key)


@pytest.mark.parametrize(
    "input_data, data_type",
    [
        ((mnemonic.split()[:-1], entropy, private_key), "mnemonic"),
        ((mnemonic.split(), KeyDataSecrets.generate().entropy, private_key), "entropy"),
        ((mnemonic.split(), entropy, KeyDataSecrets.generate().private_key), "private_key"),
    ],
)
def test_key_data_secrets_post_init(input_data: Tuple[List[str], bytes, PrivateKey], data_type: str) -> None:
    with pytest.raises(KeychainKeyDataMismatch, match=data_type):
        KeyDataSecrets(*input_data)


@pytest.mark.parametrize(
    "input_data, data_type",
    [
        ((fingerprint, G1Element(), None, KeyDataSecrets(mnemonic.split(), entropy, private_key)), "public_key"),
        ((fingerprint, G1Element(), None, None), "fingerprint"),
    ],
)
def test_key_data_post_init(
    input_data: Tuple[uint32, G1Element, Optional[str], Optional[KeyDataSecrets]], data_type: str
) -> None:
    with pytest.raises(KeychainKeyDataMismatch, match=data_type):
        KeyData(*input_data)


@pytest.mark.parametrize("include_secrets", [True, False])
def test_get_key(include_secrets: bool, get_temp_keyring: Keychain):
    keychain: Keychain = get_temp_keyring
    expected_keys = []
    # Add 10 keys and validate the result `get_key` for each of them after each addition
    for _ in range(0, 10):
        key_data = KeyData.generate()
        mnemonic_str = key_data.mnemonic_str()
        if not include_secrets:
            key_data = replace(key_data, secrets=None)
        expected_keys.append(key_data)
        # The last created key should not yet succeed in `get_key`
        with pytest.raises(KeychainFingerprintNotFound):
            keychain.get_key(expected_keys[-1].fingerprint, include_secrets)
        # Add it and validate all keys
        keychain.add_private_key(mnemonic_str)
        assert all(keychain.get_key(key_data.fingerprint, include_secrets) == key_data for key_data in expected_keys)
    # Remove 10 keys and validate the result `get_key` for each of them after each removal
    while len(expected_keys) > 0:
        delete_key = expected_keys.pop()
        keychain.delete_key_by_fingerprint(delete_key.fingerprint)
        # The removed key should no longer succeed in `get_key`
        with pytest.raises(KeychainFingerprintNotFound):
            keychain.get_key(delete_key.fingerprint, include_secrets)
        assert all(keychain.get_key(key_data.fingerprint, include_secrets) == key_data for key_data in expected_keys)


@pytest.mark.parametrize("include_secrets", [True, False])
def test_get_keys(include_secrets: bool, get_temp_keyring: Keychain):
    keychain: Keychain = get_temp_keyring
    # Should be empty on start
    assert keychain.get_keys(include_secrets) == []
    expected_keys = []
    # Add 10 keys and validate the result of `get_keys` after each addition
    for _ in range(0, 10):
        key_data = KeyData.generate()
        mnemonic_str = key_data.mnemonic_str()
        if not include_secrets:
            key_data = replace(key_data, secrets=None)
        expected_keys.append(key_data)
        keychain.add_private_key(mnemonic_str)
        assert keychain.get_keys(include_secrets) == expected_keys
    # Remove all 10 keys and validate the result of `get_keys` after each removal
    while len(expected_keys) > 0:
        delete_key = expected_keys.pop()
        keychain.delete_key_by_fingerprint(delete_key.fingerprint)
        assert keychain.get_keys(include_secrets) == expected_keys
    # Should be empty again
    assert keychain.get_keys(include_secrets) == []


def test_set_label(get_temp_keyring: Keychain) -> None:
    keychain: Keychain = get_temp_keyring
    # Generate a key and add it without label
    key_data_0 = KeyData.generate(label=None)
    keychain.add_private_key(mnemonic=key_data_0.mnemonic_str(), label=None)
    assert key_data_0 == keychain.get_key(key_data_0.fingerprint, include_secrets=True)
    # Set a label and validate it
    key_data_0 = replace(key_data_0, label="key_0")
    assert key_data_0.label is not None
    keychain.set_label(fingerprint=key_data_0.fingerprint, label=key_data_0.label)
    assert key_data_0 == keychain.get_key(fingerprint=key_data_0.fingerprint, include_secrets=True)
    # Try to add the same label for a fingerprint where don't have a key for
    with pytest.raises(KeychainFingerprintNotFound):
        keychain.set_label(fingerprint=123456, label=key_data_0.label)
    # Add a second key
    key_data_1 = KeyData.generate(label="key_1")
    assert key_data_1.label is not None
    keychain.add_private_key(key_data_1.mnemonic_str())
    # Try to set the already existing label for the second key
    with pytest.raises(KeychainLabelExists) as e:
        keychain.set_label(fingerprint=key_data_1.fingerprint, label=key_data_0.label)
    assert e.value.fingerprint == key_data_0.fingerprint
    assert e.value.label == key_data_0.label

    # Set a different label to the second key and validate it
    keychain.set_label(fingerprint=key_data_1.fingerprint, label=key_data_1.label)
    assert key_data_0 == keychain.get_key(fingerprint=key_data_0.fingerprint, include_secrets=True)
    # All added keys should still be valid with their label
    assert all(key_data in [key_data_0, key_data_1] for key_data in keychain.get_keys(include_secrets=True))


@pytest.mark.parametrize(
    "label, message",
    [
        ("", "label can't be empty or whitespace only"),
        ("   ", "label can't be empty or whitespace only"),
        ("a\nb", "label can't contain newline or tab"),
        ("a\tb", "label can't contain newline or tab"),
        ("a" * 66, "label exceeds max length: 66/65"),
        ("a" * 70, "label exceeds max length: 70/65"),
    ],
)
def test_set_label_invalid_labels(label: str, message: str, get_temp_keyring: Keychain) -> None:
    keychain: Keychain = get_temp_keyring
    key_data = KeyData.generate()
    keychain.add_private_key(key_data.mnemonic_str())
    with pytest.raises(KeychainLabelInvalid, match=message) as e:
        keychain.set_label(key_data.fingerprint, label)
    assert e.value.label == label


def test_delete_label(get_temp_keyring: Keychain) -> None:
    keychain: Keychain = get_temp_keyring
    # Generate two keys and add them to the keychain
    key_data_0 = KeyData.generate(label="key_0")
    key_data_1 = KeyData.generate(label="key_1")

    def assert_delete_raises():
        # Try to delete the labels should fail now since they are gone already
        for key_data in [key_data_0, key_data_1]:
            with pytest.raises(KeychainFingerprintNotFound) as e:
                keychain.delete_label(key_data.fingerprint)
            assert e.value.fingerprint == key_data.fingerprint

    # Should pass here since the keys are not added yet
    assert_delete_raises()

    for key in [key_data_0, key_data_1]:
        keychain.add_private_key(mnemonic=key.mnemonic_str(), label=key.label)
        assert key == keychain.get_key(key.fingerprint, include_secrets=True)
    # Delete the label of the first key, validate it was removed and make sure the other key retains its label
    keychain.delete_label(key_data_0.fingerprint)
    assert replace(key_data_0, label=None) == keychain.get_key(key_data_0.fingerprint, include_secrets=True)
    assert key_data_1 == keychain.get_key(key_data_1.fingerprint, include_secrets=True)
    # Re-add the label of the first key
    assert key_data_0.label is not None
    keychain.set_label(key_data_0.fingerprint, key_data_0.label)
    # Delete the label of the second key
    keychain.delete_label(key_data_1.fingerprint)
    assert key_data_0 == keychain.get_key(key_data_0.fingerprint, include_secrets=True)
    assert replace(key_data_1, label=None) == keychain.get_key(key_data_1.fingerprint, include_secrets=True)
    # Delete the label of the first key again, now both should have no label
    keychain.delete_label(key_data_0.fingerprint)
    assert replace(key_data_0, label=None) == keychain.get_key(key_data_0.fingerprint, include_secrets=True)
    assert replace(key_data_1, label=None) == keychain.get_key(key_data_1.fingerprint, include_secrets=True)
    # Should pass here since the key labels are both removed here
    assert_delete_raises()


@pytest.mark.parametrize("delete_all", [True, False])
def test_delete_drops_labels(get_temp_keyring: Keychain, delete_all: bool) -> None:
    keychain: Keychain = get_temp_keyring
    # Generate some keys and add them to the keychain
    labels = [f"key_{i}" for i in range(5)]
    keys = [KeyData.generate(label=label) for label in labels]
    for key_data in keys:
        keychain.add_private_key(mnemonic=key_data.mnemonic_str(), label=key_data.label)
        assert key_data == keychain.get_key(key_data.fingerprint, include_secrets=True)
        assert key_data.label is not None
        assert keychain.keyring_wrapper.get_label(key_data.fingerprint) == key_data.label
    if delete_all:
        # Delete the keys via `delete_all` and make sure no labels are left
        keychain.delete_all_keys()
        for key_data in keys:
            assert keychain.keyring_wrapper.get_label(key_data.fingerprint) is None
    else:
        # Delete the keys via fingerprint and make sure the label gets dropped
        for key_data in keys:
            keychain.delete_key_by_fingerprint(key_data.fingerprint)
            assert keychain.keyring_wrapper.get_label(key_data.fingerprint) is None
