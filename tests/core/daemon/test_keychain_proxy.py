from __future__ import annotations

import logging
from dataclasses import replace
from typing import AsyncGenerator

import pytest

from chia.daemon.keychain_proxy import KeychainProxy, connect_to_keychain_and_validate
from chia.simulator.block_tools import BlockTools
from chia.simulator.setup_services import setup_daemon
from chia.util.keychain import KeyData

TEST_KEY_1 = KeyData.generate(label="🚽🍯")
TEST_KEY_2 = KeyData.generate(label="👨‍✈️🥦")
TEST_KEY_3 = KeyData.generate(label="☕️🍬")


@pytest.fixture(scope="function")
async def keychain_proxy(get_b_tools: BlockTools) -> AsyncGenerator[KeychainProxy, None]:
    async with setup_daemon(btools=get_b_tools) as daemon:
        log = logging.getLogger("keychain_proxy_fixture")
        keychain_proxy = await connect_to_keychain_and_validate(daemon.root_path, log)
        assert keychain_proxy is not None
        yield keychain_proxy
        await keychain_proxy.close()


@pytest.fixture(scope="function")
async def keychain_proxy_with_keys(keychain_proxy: KeychainProxy) -> KeychainProxy:
    await keychain_proxy.add_private_key(TEST_KEY_1.mnemonic_str(), TEST_KEY_1.label)
    await keychain_proxy.add_private_key(TEST_KEY_2.mnemonic_str(), TEST_KEY_2.label)
    return keychain_proxy


@pytest.mark.anyio
async def test_add_private_key(keychain_proxy: KeychainProxy) -> None:
    keychain = keychain_proxy
    await keychain.add_private_key(TEST_KEY_3.mnemonic_str(), TEST_KEY_3.label)
    key = await keychain.get_key(TEST_KEY_3.fingerprint, include_secrets=True)
    assert key == TEST_KEY_3


@pytest.mark.parametrize("include_secrets", [True, False])
@pytest.mark.anyio
async def test_get_key(keychain_proxy_with_keys: KeychainProxy, include_secrets: bool) -> None:
    keychain = keychain_proxy_with_keys
    key = await keychain.get_key(TEST_KEY_1.fingerprint, include_secrets=include_secrets)
    expected_key = TEST_KEY_1 if include_secrets else replace(TEST_KEY_1, secrets=None)
    assert key == expected_key


@pytest.mark.parametrize("include_secrets", [True, False])
@pytest.mark.anyio
async def test_get_keys(keychain_proxy_with_keys: KeychainProxy, include_secrets: bool) -> None:
    keychain = keychain_proxy_with_keys
    keys = await keychain.get_keys(include_secrets=include_secrets)
    if include_secrets:
        expected_keys = [TEST_KEY_1, TEST_KEY_2]
    else:
        expected_keys = [replace(TEST_KEY_1, secrets=None), replace(TEST_KEY_2, secrets=None)]
    assert keys == expected_keys
