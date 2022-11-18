from __future__ import annotations

import logging

import pytest
import pytest_asyncio

from chia.daemon.keychain_proxy import connect_to_keychain_and_validate
from chia.simulator.setup_services import setup_daemon
from chia.util.errors import KeychainSecretsMissing

TEST_MNEMONIC_SEED_1 = (
    "toilet honey metal act put album cave useless pen dust lumber "
    "bird magnet trip unveil ranch canoe nation place since choose "
    "allow network off"
)

TEST_MNEMONIC_SEED_2 = (
    "captain broccoli humble dish sister fuel sunset horn tree couch "
    "author diamond imitate brother dilemma venue powder shaft shrimp "
    "boring lawsuit symptom uncover raven"
)

TEST_MNEMONIC_SEED_3 = (
    "coffee candy pause ginger sadness lunch mom topic sadness space "
    "around again door taxi pupil garage negative tell mutual cycle "
    "process profit course basic"
)


TEST_FINGERPRINT_1 = 1328532914
TEST_FINGERPRINT_2 = 801159606
TEST_FINGERPRINT_3 = 2524590841


@pytest_asyncio.fixture(scope="function")
async def keychain_proxy(get_b_tools):
    async for daemon in setup_daemon(btools=get_b_tools):
        log = logging.getLogger("keychain_proxy_fixture")
        keychain_proxy = await connect_to_keychain_and_validate(daemon.root_path, log)
        yield keychain_proxy
        await keychain_proxy.close()


@pytest_asyncio.fixture(scope="function")
async def keychain_proxy_with_keys(keychain_proxy):
    await keychain_proxy.add_private_key(TEST_MNEMONIC_SEED_1, "🚽🍯")
    await keychain_proxy.add_private_key(TEST_MNEMONIC_SEED_2, "👨‍✈️🥦")
    return keychain_proxy


@pytest.mark.asyncio
async def test_add_private_key(keychain_proxy):
    keychain = keychain_proxy
    await keychain.add_private_key(TEST_MNEMONIC_SEED_3, "☕️🍬")
    key = await keychain.get_key(TEST_FINGERPRINT_3, include_secrets=True)
    assert key is not None
    assert key.fingerprint == TEST_FINGERPRINT_3
    assert key.mnemonic == TEST_MNEMONIC_SEED_3.split(" ")
    assert key.label == "☕️🍬"


@pytest.mark.asyncio
async def test_get_key(keychain_proxy_with_keys):
    keychain = keychain_proxy_with_keys
    key = await keychain.get_key(TEST_FINGERPRINT_1)
    assert key is not None
    assert key.fingerprint == TEST_FINGERPRINT_1
    assert key.label == "🚽🍯"
    with pytest.raises(KeychainSecretsMissing):
        _ = key.mnemonic


@pytest.mark.asyncio
async def test_get_key_with_secrets(keychain_proxy_with_keys):
    keychain = keychain_proxy_with_keys
    key = await keychain.get_key(TEST_FINGERPRINT_1, include_secrets=True)
    assert key is not None
    assert key.fingerprint == TEST_FINGERPRINT_1
    assert key.mnemonic == TEST_MNEMONIC_SEED_1.split(" ")
    assert key.label == "🚽🍯"


@pytest.mark.asyncio
async def test_get_keys(keychain_proxy_with_keys):
    keychain = keychain_proxy_with_keys
    keys = await keychain.get_keys()
    assert len(keys) == 2
    assert keys[0].fingerprint == TEST_FINGERPRINT_1
    assert keys[0].label == "🚽🍯"
    assert keys[1].fingerprint == TEST_FINGERPRINT_2
    assert keys[1].label == "👨‍✈️🥦"
    with pytest.raises(KeychainSecretsMissing):
        _ = keys[0].mnemonic
    with pytest.raises(KeychainSecretsMissing):
        _ = keys[1].mnemonic


@pytest.mark.asyncio
async def test_get_keys_with_secrets(keychain_proxy_with_keys):
    keychain = keychain_proxy_with_keys
    keys = await keychain.get_keys(include_secrets=True)
    assert len(keys) == 2
    assert keys[0].fingerprint == TEST_FINGERPRINT_1
    assert keys[0].label == "🚽🍯"
    assert keys[0].mnemonic == TEST_MNEMONIC_SEED_1.split(" ")
    assert keys[0].entropy is not None
    assert keys[0].private_key.get_g1().get_fingerprint() == TEST_FINGERPRINT_1
    assert keys[1].fingerprint == TEST_FINGERPRINT_2
    assert keys[1].label == "👨‍✈️🥦"
    assert keys[1].mnemonic == TEST_MNEMONIC_SEED_2.split(" ")
    assert keys[1].entropy is not None
    assert keys[1].private_key.get_g1().get_fingerprint() == TEST_FINGERPRINT_2
